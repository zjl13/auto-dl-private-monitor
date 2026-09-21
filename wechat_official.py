"""WeChat Official Account template messages; credentials never enter monitor state."""
import hashlib
import math
import time
from pathlib import Path

import requests

from common import MonitorError, StateLock, atomic_json, expand, read_json


class WechatOfficial:
    API = "https://api.weixin.qq.com"

    def __init__(self, base="."):
        self.base = Path(base)
        self.session = requests.Session()
        self.session.trust_env = False

    def close(self):
        self.session.close()

    def credentials(self, settings, require_recipient=True):
        path = settings.get("credentials_file")
        if not isinstance(path, str) or not path:
            raise MonitorError("wechat_config", "公众号通知缺少 credentials_file。")
        credentials = expand(read_json(self.base / path))
        fields = ("appid", "appsecret", "openid", "template_id") if require_recipient else ("appid", "appsecret")
        if not isinstance(credentials, dict) or any(
                not isinstance(credentials.get(k), str) or not credentials[k].strip() for k in fields):
            raise MonitorError("wechat_config", "公众号凭据缺少所需字段；请检查本地密钥文件。")
        return credentials

    def validate(self, settings):
        self.credentials(settings)
        self.cache_path(settings)

        data = settings.get("data")
        if not isinstance(data, dict) or not data or any(
                not isinstance(k, str) or not k or not isinstance(v, dict)
                or not isinstance(v.get("value"), str) for k, v in data.items()):
            raise MonitorError("wechat_config", "公众号 data 必须与后台模板的字段名称和格式一致。")
        url = settings.get("url", "")
        if not isinstance(url, str) or (url and not url.startswith("https://")):
            raise MonitorError("wechat_config", "公众号消息跳转地址必须为 HTTPS。")

    def cache_path(self, settings):
        if not isinstance(settings.get("token_cache_file"), str) or not settings["token_cache_file"]:
            raise MonitorError("wechat_config", "公众号通知缺少 token_cache_file。")
        path = (self.base / settings["token_cache_file"]).resolve()
        if path == (self.base / settings["credentials_file"]).resolve():
            raise MonitorError("wechat_config", "公众号令牌缓存不能覆盖凭据文件。")
        return path

    def _request(self, settings, method, path, **kwargs):
        # Dedicated session and fixed destination prevent cloud credentials being forwarded.
        self.session.cookies.clear()
        self.session.trust_env = settings.get("trust_env", False)
        try:
            response = self.session.request(method, self.API + path,
                                            timeout=settings.get("timeout_seconds", 10),
                                            allow_redirects=False, **kwargs)
            if not 200 <= response.status_code < 300:
                raise MonitorError("wechat_http", f"微信接口 HTTP {response.status_code}。")
            payload = response.json()
        except (requests.RequestException, ValueError):
            # Neither a requests exception nor WeChat errmsg is safe to log verbatim.
            raise MonitorError("wechat_network", "微信接口连接失败或响应不是 JSON。") from None
        if not isinstance(payload, dict) or ("errcode" in payload and type(payload["errcode"]) is not int):
            raise MonitorError("wechat_response", "微信接口响应格式异常。")
        return payload

    @staticmethod
    def check_error(payload):
        code = payload.get("errcode", 0)
        if code:
            hints = {40164: "请在公众号后台核对服务器出口 IP 白名单。",
                     48001: "该账号尚无此接口权限。", 43004: "接收者需要先关注公众号。",
                     40003: "请核对该公众号对应的接收者 OpenID。",
                     40037: "请核对该公众号对应的模板 ID。",
                     45009: "接口调用额度已用尽。", 45011: "接口调用过于频繁。"}
            raise MonitorError("wechat_business", f"微信接口错误 {code}。" + hints.get(code, "请核对账号权限及模板配置。"))

    def access_token(self, settings, credentials, rejected_token=None):
        path = self.cache_path(settings)
        scope = hashlib.sha256((credentials["appid"] + "\0" + credentials["appsecret"]).encode()).hexdigest()
        # Share this file between processes using the same AppID; lock refreshes too.
        with StateLock(path):
            cached = read_json(path) if path.exists() else {}
            now = time.time()
            expiry = cached.get("expires_at") if isinstance(cached, dict) else None
            if (isinstance(cached, dict) and cached.get("scope") == scope
                    and isinstance(cached.get("access_token"), str) and cached["access_token"]
                    and type(expiry) in (int, float) and math.isfinite(expiry) and expiry > now
                    and cached["access_token"] != rejected_token):
                return cached["access_token"]
            payload = self._request(settings, "GET", "/cgi-bin/token", params={
                "grant_type": "client_credential", "appid": credentials["appid"], "secret": credentials["appsecret"]})
            self.check_error(payload)
            token, seconds = payload.get("access_token"), payload.get("expires_in")
            if not isinstance(token, str) or not token or type(seconds) is not int or seconds <= 0:
                raise MonitorError("wechat_response", "微信未返回有效的 access_token 或有效期。")
            atomic_json(path, {"scope": scope, "access_token": token,
                               "expires_at": now + seconds - min(120, seconds * 0.1)})
            return token

    def send(self, settings, data):
        credentials = self.credentials(settings)
        body = {"touser": credentials["openid"], "template_id": credentials["template_id"], "data": data}
        if settings.get("url"):
            body["url"] = settings["url"]
        token = self.access_token(settings, credentials)
        for attempt in range(2):
            payload = self._request(settings, "POST", "/cgi-bin/message/template/send",
                                    params={"access_token": token}, json=body)
            if payload.get("errcode") in (40014, 42001) and attempt == 0:
                token = self.access_token(settings, credentials, rejected_token=token)
                continue
            self.check_error(payload)
            if (type(payload.get("errcode")) is not int or payload["errcode"] != 0
                    or type(payload.get("msgid")) is not int or payload["msgid"] < 0):
                raise MonitorError("wechat_response", "微信未确认接受模板消息。")
            return
