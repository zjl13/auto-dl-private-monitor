"""HTTP API polling, browser response capture and DOM fallback."""
import copy
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

import requests
from availability import adapt_private

from common import (MonitorError, expand, get_path, integer, origin, parse_json_response,
                    read_json, set_path, validate_payload)


class ApiSource:
    def __init__(self, config, base):
        self.config, self.base = config, Path(base)
        self.api = config["api"]
        self.url = expand(self.api["url"])
        self.session = requests.Session()
        self.session.trust_env = self.api.get("trust_env", False)
        self.variables = {}
        self.logged_in = False
        self.credentials_fingerprint = None

    def close(self):
        self.session.close()

    def request(self, spec, headers=None):
        spec = expand(spec, self.variables)
        url = spec.get("url", self.url)
        if origin(url) != origin(self.url):
            raise MonitorError("config_origin", "登录步骤和资源接口必须同源；SSO 请使用浏览器登录。")
        method = spec.get("method", "GET").upper()
        if "json" in spec and "form" in spec:
            raise MonitorError("config_body", "json 和 form 请求体只能选择一种。")
        if method not in ("GET", "POST"):
            raise MonitorError("config_method", "仅支持 GET/POST 查询及显式配置的登录请求。")
        verify = expand(self.api.get("ca_bundle", True))
        if verify is False:
            raise MonitorError("config_tls", "请配置 CA 证书文件，不支持关闭 TLS 校验。")
        h = {"Accept": "application/json", "Cache-Control": "no-cache"}
        h.update(headers or {})
        h.update(spec.get("headers", {}))
        timeout = self.api.get("timeout_seconds", 20)
        try:
            response = self.session.request(
                method, url, headers=h, params=spec.get("params"),
                json=spec.get("json"), data=spec.get("form"),
                timeout=(min(10, timeout), timeout), verify=verify, allow_redirects=False)
        except requests.RequestException:
            raise MonitorError("network", "连接失败、超时或 TLS 校验失败；检查网络/VPN/CA。") from None
        return parse_json_response(response.status_code, response.content, response.headers)

    def login(self):
        login = self.config.get("auth", {}).get("login", {})
        if not login.get("enabled", False):
            return
        self.variables.clear()
        self.session.cookies.clear()
        for step in login["steps"]:
            data = self.request(step["request"])
            validate_payload(data, step.get("success"))
            for name, path in step.get("save", {}).items():
                value = get_path(data, path)
                if not isinstance(value, (str, int)) or str(value) == "":
                    raise MonitorError("login_schema", "登录响应中没有预期的票据或令牌。")
                self.variables[name] = value
        self.logged_in = True

    def auth_headers(self):
        auth = self.config.get("auth", {})
        headers = {}
        if auth.get("credentials_file"):
            saved = read_json(self.base / auth["credentials_file"])
            if origin(saved["origin"]) != origin(self.url):
                raise MonitorError("credential_origin", "会话文件绑定的接口域名/端口不匹配。")
            fingerprint = json.dumps(saved, sort_keys=True)
            if fingerprint != self.credentials_fingerprint:
                self.session.cookies.clear()
                self.credentials_fingerprint = fingerprint
            headers.update(saved["headers"])
        headers.update(expand(auth.get("headers", {}), self.variables))
        csrf = auth.get("csrf", {})
        if csrf.get("cookie_name"):
            cookie = self.session.cookies.get_dict().get(csrf["cookie_name"])
            if not cookie:
                from http.cookies import SimpleCookie
                parsed = SimpleCookie()
                parsed.load(next((v for k, v in headers.items() if k.lower() == "cookie"), ""))
                entry = parsed.get(csrf["cookie_name"])
                cookie = entry.value if entry else None
            if not cookie:
                raise MonitorError("csrf", "缺少 CSRF Cookie；先配置登录/会话。")
            from urllib.parse import unquote
            headers[csrf["header_name"]] = unquote(cookie) if csrf.get("url_decode", False) else cookie
        return headers

    def fetch(self):
        login = self.config.get("auth", {}).get("login", {})
        if login.get("enabled") and not self.logged_in:
            self.login()
        try:
            return adapt_private(self.fetch_all(), self.config,
                                 lambda spec: self.request(spec, self.auth_headers()))
        except MonitorError as error:
            if error.code == "auth" and login.get("enabled"):
                self.logged_in = False
                self.login()  # At most one re-login per poll; no MFA bypass.
                return adapt_private(self.fetch_all(), self.config,
                                     lambda spec: self.request(spec, self.auth_headers()))
            raise

    def fetch_all(self):
        pagination = self.api.get("pagination", {})
        mode = pagination.get("mode", "none")
        if mode not in ("none", "page", "cursor"):
            raise MonitorError("config", "pagination.mode 只支持 none/page/cursor。")
        all_items, seen_pages = [], set()
        current = pagination.get("start", 1) if mode == "page" else pagination.get("initial_cursor")
        expected_total = None
        for _ in range(pagination.get("max_pages", 100)):
            spec = copy.deepcopy(self.api["request"])
            if mode != "none":
                target = spec.setdefault(pagination.get("location", "json"), {})
                if current is not None:
                    set_path(target, pagination["parameter"], current)
                if pagination.get("size_parameter"):
                    set_path(target, pagination["size_parameter"], pagination["page_size"])
            data = self.request(spec, self.auth_headers())
            validate_payload(data, self.api.get("success"))
            items = get_path(data, self.api["items_path"])
            if not isinstance(items, list):
                raise MonitorError("schema", "items_path 必须指向资源数组。")
            if pagination.get("total_path"):
                total = integer(get_path(data, pagination["total_path"]))
                if expected_total is not None and total != expected_total:
                    raise MonitorError("pagination_changed", "分页期间资源总数改变；丢弃不完整快照，下轮重试。")
                expected_total = total
            signature = json.dumps(items, sort_keys=True, ensure_ascii=False)
            if items and signature in seen_pages:
                raise MonitorError("pagination_repeat", "分页返回重复内容；请检查分页参数。")
            seen_pages.add(signature)
            all_items.extend(items)
            if expected_total is not None and len(all_items) > expected_total:
                raise MonitorError("pagination_count", "分页记录数超过接口总数；检查总数路径。")
            if mode == "none" or (expected_total is not None and len(all_items) == expected_total):
                break
            if mode == "page":
                if len(items) < pagination["page_size"]:
                    break
                current += 1
            else:
                next_cursor = get_path(data, pagination["next_cursor_path"])
                if next_cursor in (None, ""):
                    break
                if next_cursor == current:
                    raise MonitorError("pagination_repeat", "分页游标没有前进。")
                current = next_cursor
        else:
            raise MonitorError("pagination_limit", "达到分页上限；不能把截断数据作为完整快照。")
        if expected_total is not None and len(all_items) != expected_total:
            raise MonitorError("pagination_incomplete", "未取完接口声明的全部记录；本轮不更新状态。")
        return all_items


class BrowserSource:
    """Use the page's own logged-in requests, or read configured visible fields."""
    def __init__(self, config, base):
        self.config, self.base = config, Path(base)
        self.settings = config["browser"]
        self.pw = self.browser = self.context = self.page = None
        self.state_stamp = None

    def close(self):
        if self.browser:
            self.browser.close()
        if self.pw:
            self.pw.stop()
        self.pw = self.browser = self.context = self.page = None

    def start(self):
        state_file = self.base / self.settings["storage_state"]
        try:
            stamp = state_file.stat().st_mtime_ns
        except OSError:
            raise MonitorError("browser_session", "请先运行 browser_login.py 保存浏览器会话。") from None
        if self.page and stamp == self.state_stamp:
            return
        self.close()
        from playwright.sync_api import sync_playwright
        self.pw = sync_playwright().start()
        self.browser = self.pw.chromium.launch(
            headless=self.settings.get("headless", True),
            channel=self.settings.get("channel") or None,
        )
        self.context = self.browser.new_context(storage_state=str(state_file), service_workers="block")
        self.page = self.context.new_page()
        self.page.set_default_timeout(self.settings.get("timeout_seconds", 30) * 1000)
        self.state_stamp = stamp

    def check_login(self):
        selector = self.settings.get("login_selector")
        if selector and self.page.locator(selector).count() and self.page.locator(selector).first.is_visible():
            raise MonitorError("auth", "浏览器进入登录页；重新运行 browser_login.py。")
        allowed = origin(expand(self.settings["page_url"]))
        if origin(self.page.url) != allowed:
            raise MonitorError("auth", "页面跳转到其他站点，可能需要重新登录。")

    def fetch(self):
        try:
            self.start()
            if self.config["source"] == "browser_network":
                return adapt_private(self.network(), self.config)
            return self.dom()
        except MonitorError:
            raise
        except ImportError:
            raise MonitorError("browser_dependency", "请安装 requirements-browser.txt 和 Playwright Chromium。") from None
        except Exception:
            # Browser exception strings may include URLs or tokens; never log them.
            self.close()
            raise MonitorError("browser", "浏览器读取失败；检查登录状态、响应匹配、选择器和浏览器安装。") from None

    def network(self):
        match = self.settings["response_match"]
        def predicate(response):
            parts = urlsplit(response.url)
            return (origin(response.url) == origin(expand(match["origin"]))
                    and parts.path == match["path"]
                    and response.request.method == match.get("method", "POST").upper())
        with self.page.expect_response(predicate) as pending:
            self.page.goto(expand(self.settings["page_url"]), wait_until="domcontentloaded")
        self.check_login()
        response = pending.value
        data = parse_json_response(response.status, response.body(), response.headers)
        validate_payload(data, self.config["api"].get("success"))
        items = get_path(data, self.config["api"]["items_path"])
        if not isinstance(items, list):
            raise MonitorError("schema", "浏览器响应中的 items_path 不是数组。")
        total_path = self.settings.get("total_path")
        if total_path and integer(get_path(data, total_path)) != len(items):
            raise MonitorError("browser_partial", "页面响应只有部分记录；改用 API 分页或调整页面查询范围。")
        if not total_path and not self.settings.get("single_page_confirmed", False):
            raise MonitorError("browser_scope", "需配置 total_path 或确认 single_page_confirmed。")
        return items

    def dom(self):
        s = self.settings["dom"]
        availability = self.config.get("availability", {})
        if availability.get("adapter") == "autodl_private" and availability.get("sharing") != "disabled":
            raise MonitorError("dom_sharing", "私有云 DOM 模式只支持显式关闭多租，并读取 sharing 列核验；多租请使用 API。")
        if not s.get("single_page_confirmed", False):
            raise MonitorError("browser_scope", "DOM 模式需明确确认监控范围为完整单页。")
        self.page.goto(expand(self.settings["page_url"]), wait_until="domcontentloaded")
        self.check_login()
        self.page.locator(s["ready_selector"]).wait_for(state="visible")
        if s.get("loading_selector"):
            self.page.locator(s["loading_selector"]).wait_for(state="hidden")
        self.check_login()
        if s.get("empty_selector") and self.page.locator(s["empty_selector"]).first.is_visible():
            return []
        rows = self.page.locator(s["row_selector"])
        if rows.count() == 0:
            # Wait for the first asynchronous table response instead of treating
            # a visible table skeleton as a completed resource snapshot.
            rows.first.wait_for(state="visible")
        if rows.count() == 0:
            raise MonitorError("dom_empty", "未找到资源行；不能区分空表、加载中或选择器失效。")
        result = []
        for i in range(rows.count()):
            row = rows.nth(i)
            record = {}
            if s.get("hover_selector"):
                row.locator(s["hover_selector"]).hover()
            for name, rule in s["fields"].items():
                scope = self.page if rule.get("scope") == "page" else row
                loc = scope.locator(rule["selector"]) if rule.get("selector") else row
                loc.wait_for(state="visible")
                value = loc.get_attribute(rule["attribute"]) if rule.get("attribute") else loc.inner_text()
                if value is None:
                    raise MonitorError("dom_field", "DOM 属性缺失；检查字段选择器。")
                if rule.get("regex"):
                    found = re.search(rule["regex"], value)
                    if not found:
                        raise MonitorError("dom_field", "DOM 字段格式变化；正则无法匹配。")
                    value = found.group(rule.get("group", 1))
                record[name] = value.strip()
            if availability.get("adapter") == "autodl_private" and record.get("sharing") != "未开启":
                raise MonitorError("dom_sharing", "未能确认该主机的多租状态为未开启；不生成卡数快照。")
            result.append(record)
            if s.get("hover_selector"):
                self.page.mouse.move(0, 0)
        return result
