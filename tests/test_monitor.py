import copy
import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from common import (MonitorError, StateLock, atomic_json, expand, normalize, parse_json_response,
                    read_json, select_snapshot)
from monitor import Notifier, run, update_failure, update_success
from sources import ApiSource, BrowserSource
from availability import adapt_private

ROOT = Path(__file__).resolve().parents[1]


def config():
    return read_json(ROOT / "config.private.example.json")


def raw(available=0, identifier="one"):
    return {"machine_type": "gpu", "machine_id": identifier, "gpu_name": "NVIDIA RTX 4090",
            "gpu": {"idle": available, "total": 8}, "gpu_max_instance_num": 1}


def snapshot(available):
    c = config()
    return select_snapshot(normalize([raw(available)], c["mapping"]), c["filters"])


class MockHandler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def reply(self, data, status=200, headers=None):
        data = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/page":
            html = '''<!doctype html><html><body><table id="rows"><tbody></tbody></table>
            <script>fetch('/list', {method:'POST',headers:{'Content-Type':'application/json'},body:'{}'})
            .then(r=>r.json()).then(d=>{document.querySelector('tbody').innerHTML=d.data.list.map(
              x=>`<tr data-id="${x.machine_id}"><td class="model">${x.gpu_name}</td><td class="free">${x.gpu.idle}</td><td class="total">8</td></tr>`).join('');
              document.body.setAttribute('data-ready','true');});</script></body></html>'''
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(html.encode())
        else:
            self.reply({}, 404)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        self.server.calls.append((self.path, dict(self.headers), body))
        if self.path == "/login":
            self.server.logins += 1
            self.reply({"code": "Success", "data": {"token": "fresh"}}, headers={"Set-Cookie": "sid=private; Path=/"})
        elif self.path == "/hook":
            self.reply({"code": 0}, self.server.hook_status)
        elif self.server.failure:
            status, data = self.server.failure
            self.reply(data, status)
        elif self.server.require_auth and self.headers.get("Authorization") != "fresh":
            self.reply({"code": "AuthorizeFailed"}, 401)
        else:
            page = body.get("page_index", 1)
            size = body.get("page_size", len(self.server.rows) or 10)
            start = (page - 1) * size
            self.reply({"code": "Success", "data": {"list": self.server.rows[start:start+size],
                                                        "result_total": len(self.server.rows)}})


class CoreTests(unittest.TestCase):
    def test_single_process_state_lock(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "state.json"
            with StateLock(path):
                with self.assertRaises(MonitorError):
                    with StateLock(path):
                        pass
            with StateLock(path):
                pass  # Lock becomes available after release.

    def test_shared_exclusive_vs_allocatable(self):
        c = config()
        row = raw(99)
        row["gpu_max_instance_num"] = 3
        cards = [
            {"gpu_uuid": "empty", "reserved": False, "gpu_bindings": []},
            {"gpu_uuid": "partial", "reserved": False, "gpu_bindings": [{"instance_uuid": "running"}]},
            {"gpu_uuid": "full", "reserved": True, "gpu_bindings": [{"instance_uuid": "running"}]}
        ]
        calls = []
        def fetch(spec):
            calls.append(spec)
            return {"code": "Success", "data": {"list": cards}}
        result = adapt_private([row], c, fetch)
        self.assertEqual(result[0]["gpu"], {"idle": 1, "total": 3})
        self.assertEqual(row["gpu"]["idle"], 99)  # Input is never mutated.
        self.assertEqual(calls[0]["json"]["machine_id"], "one")
        c["availability"]["free_definition"] = "allocatable"
        self.assertEqual(adapt_private([row], c, fetch)[0]["gpu"]["idle"], 2)

    def test_sharing_switches_and_permissions(self):
        c = config()
        self.assertEqual(adapt_private([raw(2)], c)[0]["gpu"]["idle"], 2)
        shared = raw(2)
        shared["gpu_max_instance_num"] = 2
        c["availability"]["sharing"] = "disabled"
        with self.assertRaises(MonitorError) as caught:
            adapt_private([shared], c)
        self.assertEqual(caught.exception.code, "sharing_mismatch")
        c["availability"]["sharing"] = "enabled"
        with self.assertRaises(MonitorError) as caught:
            adapt_private([raw(2)], c, lambda _: {"code": "PermissionDenied"})
        self.assertEqual(caught.exception.code, "api_business")
        with self.assertRaises(MonitorError):
            adapt_private([shared], c)

    def test_shared_missing_binding_and_duplicate_uuid(self):
        c = config()
        c["availability"]["sharing"] = "enabled"
        data = {"code": "Success", "data": {"list": [{"gpu_uuid": "a", "reserved": False}]}}
        with self.assertRaises(MonitorError):
            adapt_private([raw()], c, lambda _: data)
        c["availability"]["free_definition"] = "allocatable"
        data["data"]["list"].append({"gpu_uuid": "a", "reserved": False})
        with self.assertRaises(MonitorError):
            adapt_private([raw()], c, lambda _: data)

    def test_legacy_binding_and_missing_capacity(self):
        c = config()
        c["availability"]["sharing"] = "enabled"
        data = {"code": "Success", "data": {"list": [
            {"gpu_uuid": "a", "reserved": False, "instance_uuid": ""},
            {"gpu_uuid": "b", "reserved": False, "instance_uuid": "running"}]}}
        self.assertEqual(adapt_private([raw()], c, lambda _: data)[0]["gpu"]["idle"], 1)
        c["availability"]["sharing"] = "auto"
        item = raw()
        del item["gpu_max_instance_num"]
        with self.assertRaises(MonitorError):
            adapt_private([item], c)

    def test_changes_and_error_recovery(self):
        state = {}
        self.assertEqual(update_success(state, snapshot(0)), [])
        self.assertEqual(update_success(state, snapshot(2))[0]["type"], "resource_change")
        self.assertEqual(update_success(state, snapshot(2)), [])
        saved = copy.deepcopy(state["snapshot"])
        self.assertEqual(len(update_failure(state, MonitorError("network", "failed"))), 1)
        self.assertEqual(update_failure(state, MonitorError("network", "failed")), [])
        self.assertEqual(state["snapshot"], saved)
        self.assertEqual(update_success(state, snapshot(2))[0]["type"], "recovered")
        self.assertEqual(update_success(state, snapshot(0))[0]["type"], "resource_change")
        self.assertFalse(state["snapshot"]["available"])

    def test_missing_free_not_zero(self):
        row = raw()
        del row["gpu"]["idle"]
        with self.assertRaises(MonitorError):
            normalize([row], config()["mapping"])

    def test_invalid_and_duplicate_counts(self):
        for value in (-1, True, "NaN", None, "2 cards", 9):
            with self.subTest(value=value), self.assertRaises(MonitorError):
                normalize([raw(value)], config()["mapping"])
        with self.assertRaises(MonitorError):
            normalize([raw(), raw()], config()["mapping"])

    def test_filter_and_per_machine_threshold(self):
        c = config()
        rows = normalize([raw(2, "a"), raw(2, "b")], c["mapping"])
        c["filters"]["min_free_per_resource"] = 4
        self.assertFalse(select_snapshot(rows, c["filters"])["available"])
        c["filters"]["min_free_per_resource"] = 1
        c["filters"]["min_total_free_per_model"] = 4
        self.assertTrue(select_snapshot(rows, c["filters"])["available"])
        c["filters"]["models"] = ["A100"]
        self.assertFalse(select_snapshot(rows, c["filters"])["available"])

    def test_cpu_excluded(self):
        row = {"machine_type": "cpu"}
        self.assertEqual(normalize([row], config()["mapping"]), {})

    def test_cards_require_unbound(self):
        mapping = {"mode": "cards", "fields": {"id": "uuid", "model": "model", "status": "reserved"},
                   "idle_values": [False], "idle_require": {"bindings": [[]]}}
        rows = [{"uuid": "1", "model": "A40", "reserved": False, "bindings": []},
                {"uuid": "2", "model": "A40", "reserved": False, "bindings": ["occupied"]}]
        self.assertEqual(sum(r["free"] for r in normalize(rows, mapping).values()), 1)

    def test_error_body_is_not_logged(self):
        for status, body, code in [(401, "SECRET", "auth"), (302, "SECRET", "redirect"),
                                   (200, "<html>SECRET</html>", "not_json")]:
            with self.assertRaises(MonitorError) as caught:
                parse_json_response(status, body, {})
            self.assertEqual(caught.exception.code, code)
            self.assertNotIn("SECRET", str(caught.exception))

    def test_retry_after_and_env(self):
        with self.assertRaises(MonitorError) as caught:
            parse_json_response(429, "", {"Retry-After": "120"})
        self.assertEqual(caught.exception.retry_after, 120)
        with patch.dict(os.environ, {"TEST_TOKEN": "abc"}):
            self.assertEqual(expand({"h": "Bearer ${TEST_TOKEN}"}), {"h": "Bearer abc"})
        with self.assertRaises(MonitorError):
            expand("${MISSING_TEST_987321}")


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), MockHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def setUp(self):
        self.server.rows = [raw(1, "a"), raw(0, "b"), raw(2, "c")]
        self.server.calls, self.server.failure = [], None
        self.server.require_auth, self.server.logins, self.server.hook_status = False, 0, 200
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.c = config()
        self.c["api"]["url"] = self.url + "/list"
        self.c["api"]["pagination"]["page_size"] = 2
        self.c["auth"] = {"headers": {"Authorization": "secret"}}

    def source(self):
        source = ApiSource(self.c, self.tmp.name)
        self.addCleanup(source.close)
        return source

    def test_real_http_pagination(self):
        self.assertEqual(len(self.source().fetch()), 3)
        self.assertEqual([x[2]["page_index"] for x in self.server.calls], [1, 2])

    def test_pagination_limit_not_partial(self):
        self.c["api"]["pagination"]["max_pages"] = 1
        with self.assertRaises(MonitorError) as caught:
            self.source().fetch()
        self.assertEqual(caught.exception.code, "pagination_limit")

    def test_application_auth_failure(self):
        self.server.failure = (200, {"code": "AuthorizeFailed"})
        with self.assertRaises(MonitorError) as caught:
            self.source().fetch()
        self.assertEqual(caught.exception.code, "auth")

    def test_login_and_relogin(self):
        self.server.require_auth = True
        self.c["auth"] = {"headers": {"Authorization": "${LOGIN_TOKEN}"}, "login": {
            "enabled": True, "steps": [{"request": {"url": self.url + "/login", "method": "POST", "json": {}},
                                        "save": {"LOGIN_TOKEN": "data.token"}}]}}
        source = self.source()
        self.assertEqual(len(source.fetch()), 3)
        source.variables["LOGIN_TOKEN"] = "expired"
        self.assertEqual(len(source.fetch()), 3)
        self.assertEqual(self.server.logins, 2)

    def test_credentials_reload_and_origin(self):
        path = Path(self.tmp.name) / "creds.json"
        self.c["auth"] = {"credentials_file": "creds.json"}
        source = self.source()
        atomic_json(path, {"origin": self.url, "headers": {"Authorization": "one"}})
        source.fetch()
        atomic_json(path, {"origin": self.url, "headers": {"Authorization": "two"}})
        source.fetch()
        self.assertEqual(self.server.calls[-1][1]["Authorization"], "two")
        atomic_json(path, {"origin": "https://other.invalid", "headers": {}})
        with self.assertRaises(MonitorError):
            source.fetch()

    def test_no_auth_leak_to_webhook_and_retry(self):
        self.c["notifications"]["webhook"] = {"enabled": True, "url": self.url + "/hook",
                                                "success": {"path": "code", "values": [0]}}
        self.source().fetch()
        notifier = Notifier(self.c)
        self.addCleanup(notifier.close)
        pending = [{"id": "fixed-id", "type": "change", "time": "now", "message": "available"}]
        self.server.hook_status = 503
        notifier.deliver(pending)
        self.assertEqual(len(pending), 1)
        self.server.hook_status = 200
        notifier.deliver(pending)
        self.assertEqual(pending, [])
        headers = self.server.calls[-1][1]
        self.assertNotIn("Authorization", headers)
        self.assertNotIn("Cookie", headers)

    def test_snapshot_survives_failure_and_restart(self):
        path = Path(self.tmp.name) / "config.json"
        atomic_json(path, self.c)
        self.assertEqual(run(path, once=True), 0)
        first = read_json(Path(self.tmp.name) / self.c["state_file"])["snapshot"]
        self.server.failure = (500, {})
        self.assertEqual(run(path, once=True), 1)
        self.assertEqual(read_json(Path(self.tmp.name) / self.c["state_file"])["snapshot"], first)
        self.server.failure = None
        self.assertEqual(run(path, once=True), 0)

    @unittest.skipUnless(os.environ.get("TEST_BROWSER") == "1", "Set TEST_BROWSER=1 for local Chromium tests")
    def test_browser_network_and_dom(self):
        self.server.rows = [raw(2, "a")]
        self.c["browser"].update({"page_url": self.url + "/page", "login_selector": "#login",
                                      "storage_state": "browser.json", "timeout_seconds": 5,
                                      "response_match": {"origin": self.url, "path": "/list", "method": "POST"}})
        atomic_json(Path(self.tmp.name) / "browser.json", {"cookies": [], "origins": []})
        self.c["source"] = "browser_network"
        source = BrowserSource(self.c, self.tmp.name)
        self.addCleanup(source.close)
        self.assertEqual(source.fetch()[0]["gpu"]["idle"], 2)
        self.c["source"] = "browser_dom"
        self.c["availability"] = {"adapter": "none"}
        self.c["browser"]["dom"] = {
            "single_page_confirmed": True, "ready_selector": "body[data-ready]", "row_selector": "#rows tbody tr",
            "fields": {"id": {"attribute": "data-id"}, "model": {"selector": ".model"},
                       "free": {"selector": ".free"}, "total": {"selector": ".total"}}}
        self.assertEqual(source.fetch()[0]["free"], "2")


if __name__ == "__main__":
    unittest.main()
