#!/usr/bin/env python3
"""Interactive login plus capture of ONE configured resource-list endpoint."""
import argparse
import sys
import threading
from pathlib import Path
from urllib.parse import urlsplit

from common import MonitorError, atomic_json, expand, origin, read_json


def capture(config_file, save_sample=False):
    from playwright.sync_api import sync_playwright
    config_file = Path(config_file).resolve()
    config, base = read_json(config_file), config_file.parent
    settings = config["browser"]
    api_url = expand(config["api"]["url"])
    endpoint = urlsplit(api_url)
    state_file = base / settings["storage_state"]
    credentials_file = base / config.get("auth", {}).get("credentials_file", ".secrets/credentials.json")
    page_url = expand(settings["page_url"])
    if origin(api_url) != origin(page_url):
        raise MonitorError("origin", "采集工具要求页面和 API 同源；跨源部署请手工配置认证。")
    finished = threading.Event()
    captured = {}
    responses = {}
    print("浏览器将打开。请自行登录、选择正确租户，并进入主机列表。")
    print("可在页面操作分页/刷新，以触发资源查询。完成后回到终端按回车保存。")
    print("会话和捕获信息仅写入本地 .secrets；不要分享此目录。", flush=True)

    def wait_for_enter():
        try:
            input()
        except EOFError:
            pass
        finished.set()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        try:
            context = browser.new_context(storage_state=str(state_file) if state_file.exists() else None)
            page = context.new_page()
            def on_response(response):
                p = urlsplit(response.url)
                request = response.request
                if (origin(response.url) != origin(api_url) or p.path != endpoint.path
                        or request.method != config["api"]["request"].get("method", "POST").upper()):
                    return
                try:
                    body = response.json()
                    from common import validate_payload
                    validate_payload(body, config["api"].get("success"))
                    if not 200 <= response.status < 300:
                        return
                    allowed = {h.casefold() for h in settings.get("capture_headers", ["Authorization", "Cookie", "X-CSRF-Token", "X-XSRF-Token"])}
                    headers = {k: v for k, v in request.all_headers().items() if k.casefold() in allowed}
                    captured.clear()
                    captured.update({"origin": origin(api_url), "headers": headers})
                    responses["sample"] = body
                    responses["request"] = {"method": request.method,
                                            "url": response.url, "body": request.post_data}
                    print("已捕获一条成功的资源列表响应及其认证头（内容不显示）。", flush=True)
                except Exception:
                    print("发现目标接口，但响应未通过成功校验；请检查登录状态。", flush=True)
            context.on("response", on_response)
            page.goto(page_url, wait_until="domcontentloaded")
            threading.Thread(target=wait_for_enter, daemon=True).start()
            while not finished.is_set():
                page.wait_for_timeout(200)
            # storage_state includes cookies/localStorage/IndexedDB, not sessionStorage.
            state = context.storage_state(indexed_db=True)
            atomic_json(state_file, state)
            if captured:
                atomic_json(credentials_file, captured)
                atomic_json(base / ".secrets/captured-request.json", responses["request"])
                if save_sample:
                    atomic_json(base / ".secrets/sample-response.json", responses["sample"])
                print("已保存浏览器会话、API 认证头及请求参数。可以运行 monitor.py --dry-run。")
            else:
                print("已保存浏览器会话，但未捕获成功的资源接口；请核对 api.url 后重新运行。")
                return 1
        finally:
            browser.close()
    return 0


def main():
    parser = argparse.ArgumentParser(description="人工登录私有云并保存资源查询会话")
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--save-sample", action="store_true", help="额外保存目标接口响应到本地 .secrets")
    args = parser.parse_args()
    try:
        return capture(args.config, args.save_sample)
    except KeyboardInterrupt:
        print("已取消。")
        return 0
    except MonitorError as error:
        print(str(error))
        return 2
    except Exception:
        print("登录采集失败。检查配置、网络和 Playwright Chromium 安装；不输出可能包含令牌的异常详情。")
        return 2


if __name__ == "__main__":
    sys.exit(main())
