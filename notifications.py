"""Independent outbound notification clients; no private cloud credentials here."""
import os
import re
import time
from pathlib import Path

import requests

from common import MonitorError, expand, read_json, validate_payload
from wechat_official import WechatOfficial


def render_template(value, ev):
    if isinstance(value, dict):
        return {k: render_template(v, ev) for k, v in value.items()}
    if isinstance(value, list):
        return [render_template(v, ev) for v in value]
    if isinstance(value, str):
        for k in ("id", "type", "time", "message", "title"):
            replacement = (ev["message"].splitlines() or [""])[0][:32] if k == "title" else ev[k]
            value = value.replace("{{" + k + "}}", str(replacement))
    return value


def validate_sendkey(value):
    if not isinstance(value, str) or not re.fullmatch(r"SCT[A-Za-z0-9]+", value):
        raise MonitorError("sendkey", "需要 Server酱 Turbo 的 SCT 开头 SendKey；不支持用于独立 App 的 sctp Key。")
    return value


class Notifier:
    def __init__(self, config, base=".", logger=print):
        n = config.get("notifications", {})
        self.channels = {name: n[name] for name in ("webhook", "serverchan", "wechat_official")
                         if n.get(name, {}).get("enabled", False)}
        self.base, self.log = Path(base), logger
        self.not_before = {}
        self.session = requests.Session()
        self.session.trust_env = False
        self.wechat = WechatOfficial(base) if "wechat_official" in self.channels else None

    def close(self):
        self.session.close()
        if self.wechat:
            self.wechat.close()

    def sendkey(self, settings):
        value = os.environ.get(settings.get("sendkey_env", "SERVERCHAN_SENDKEY"), "").strip()
        if not value and settings.get("sendkey_file"):
            path = self.base / settings["sendkey_file"]
            if path.exists():
                value = read_json(path).get("sendkey", "")
        if not value:
            raise MonitorError("sendkey", "未设置微信推送密钥；运行 setup_wechat.py 或设置 SERVERCHAN_SENDKEY。")
        return validate_sendkey(value)

    def validate(self):
        for name, raw in self.channels.items():
            settings = expand(raw)
            if name == "serverchan":
                self.sendkey(settings)
            elif name == "wechat_official":
                self.wechat.validate(settings)
            elif not settings.get("url"):
                raise MonitorError("webhook", "缺少 webhook URL。")
            for field, default in (("min_interval_seconds", 60), ("retry_seconds", 900), ("timeout_seconds", 10)):
                value = settings.get(field, default)
                if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 1:
                    raise MonitorError("notification_config", f"通知配置 {field} 必须至少为 1 秒。")

    def send(self, name, raw, ev):
        settings = expand(raw)
        if name == "wechat_official":
            self.wechat.send(settings, render_template(settings["data"], ev))
            return
        self.session.cookies.clear()
        self.session.trust_env = settings.get("trust_env", False)
        kwargs = {"timeout": settings.get("timeout_seconds", 10), "allow_redirects": False}
        if name == "serverchan":
            url = f"https://sctapi.ftqq.com/{self.sendkey(settings)}.send"
            # Keep the title single-line and short; no credential or endpoint in it.
            title = ev["message"].splitlines()[0][:32]
            body = {"title": title, "desp": ev["message"] + f"\n\n时间：{ev['time']}\n\n事件：{ev['id']}"}
            if settings.get("channel"):
                body["channel"] = settings["channel"]
            r = self.session.post(url, data=body, **kwargs)
        else:
            payload = render_template(settings.get("template", {
                "id": "{{id}}", "type": "{{type}}", "time": "{{time}}", "message": "{{message}}"}), ev)
            r = self.session.post(settings["url"], headers=settings.get("headers", {}), json=payload, **kwargs)
        if not 200 <= r.status_code < 300:
            raise MonitorError("notification_http", f"通知服务 HTTP {r.status_code}")
        if name == "serverchan":
            data = r.json()
            if not isinstance(data, dict) or type(data.get("code")) is not int or data["code"] != 0:
                raise MonitorError("serverchan_business", "Server酱未接受通知；检查 SendKey、通道和发送额度。")
        elif settings.get("success"):
            validate_payload(r.json(), settings["success"])

    def deliver(self, pending):
        if not self.channels:
            pending.clear()
            return
        blocked = set()
        for ev in pending[:10]:
            delivered = ev.setdefault("_delivered", [])
            for name, settings in self.channels.items():
                if name in delivered or name in blocked:
                    continue
                now = time.time()
                due = max(self.not_before.get(name, 0), ev.get("_retry_at", {}).get(name, 0))
                if now < due:
                    blocked.add(name)
                    continue
                try:
                    self.send(name, settings, ev)
                except (requests.RequestException, MonitorError, ValueError, TypeError, OSError) as error:
                    # No raw exception: requests errors can contain the secret URL.
                    self.log(f"{name} 提醒发送失败；事件已保留，请检查通道、凭据或额度。")
                    if name == "wechat_official" and isinstance(error, MonitorError):
                        self.log(str(error))  # Native client errors contain only sanitized details.
                    if name in ("serverchan", "wechat_official"):
                        ev.setdefault("_retry_at", {})[name] = now + settings.get("retry_seconds", 900)
                    blocked.add(name)
                    continue
                delivered.append(name)
                ev.get("_retry_at", {}).pop(name, None)
                self.log(f"{name} 已接受通知。")
                if name in ("serverchan", "wechat_official"):
                    self.not_before[name] = now + settings.get("min_interval_seconds", 60)
            if all(name in delivered for name in self.channels):
                pending.remove(ev)
