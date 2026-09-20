import copy
import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

import requests

from common import MonitorError, atomic_json, read_json
from monitor import event, notification_test, run
from notifications import Notifier
from setup_wechat import configure


class WechatTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.key = "SCT123TESTONLY"
        atomic_json(self.base / "key.json", {"sendkey": self.key})
        self.config = {"notifications": {"serverchan": {
            "enabled": True, "sendkey_env": "TEST_WECHAT_KEY", "sendkey_file": "key.json",
            "retry_seconds": 900, "min_interval_seconds": 60}}}
        self.messages = []
        self.notifier = Notifier(self.config, self.base, self.messages.append)
        self.addCleanup(self.notifier.close)
        self.env = patch.dict(os.environ, {}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)

    def response(self, code=0, status=200):
        response = Mock(status_code=status)
        response.json.return_value = {"code": code}
        return response

    def test_native_form_and_no_private_credentials(self):
        self.config["auth"] = {"headers": {"Authorization": "PRIVATE_TOKEN", "Cookie": "private=secret"}}
        self.notifier.validate()
        ev = event("notification_test", "微信通知测试\n第二行")
        pending = [ev]
        with patch.object(self.notifier.session, "post", return_value=self.response()) as send:
            self.notifier.deliver(pending)
        self.assertEqual(pending, [])
        self.assertEqual(send.call_args.args[0], f"https://sctapi.ftqq.com/{self.key}.send")
        kwargs = send.call_args.kwargs
        self.assertNotIn("json", kwargs)
        self.assertNotIn("headers", kwargs)
        self.assertFalse(kwargs["allow_redirects"])
        self.assertEqual(kwargs["data"]["title"], "微信通知测试")
        self.assertNotIn("PRIVATE_TOKEN", str(kwargs))

    def test_business_failure_backoff_survives_restart(self):
        pending = [event("change", "测试")]
        with patch("notifications.time.time", return_value=1000), patch.object(
                self.notifier.session, "post", return_value=self.response(code=99)) as send:
            self.notifier.deliver(pending)
            self.notifier.deliver(pending)
        self.assertEqual(send.call_count, 1)
        self.assertEqual(pending[0]["_retry_at"]["serverchan"], 1900)
        restored = copy.deepcopy(pending)
        another = Notifier(self.config, self.base)
        self.addCleanup(another.close)
        with patch("notifications.time.time", return_value=1899), patch.object(another.session, "post") as send:
            another.deliver(restored)
        send.assert_not_called()
        with patch("notifications.time.time", return_value=1901), patch.object(
                another.session, "post", return_value=self.response()):
            another.deliver(restored)
        self.assertEqual(restored, [])

    def test_http_200_false_is_not_success(self):
        pending = [event("change", "测试")]
        with patch.object(self.notifier.session, "post", return_value=self.response(code=False)):
            self.notifier.deliver(pending)
        self.assertEqual(len(pending), 1)

    def test_secret_not_in_failure_log(self):
        with patch.object(self.notifier.session, "post", side_effect=requests.ConnectionError(self.key)):
            self.notifier.deliver([event("change", "测试")])
        self.assertNotIn(self.key, "".join(self.messages))

    def test_channels_retry_independently(self):
        self.config["notifications"]["webhook"] = {"enabled": True, "url": "https://example.invalid/hook"}
        notifier = Notifier(self.config, self.base)
        self.addCleanup(notifier.close)
        pending = [event("change", "测试")]
        with patch("notifications.time.time", return_value=1000), patch.object(
                notifier.session, "post", side_effect=[self.response(), self.response(code=1)]) as send:
            notifier.deliver(pending)
        self.assertEqual(send.call_count, 2)
        self.assertEqual(pending[0]["_delivered"], ["webhook"])
        with patch("notifications.time.time", return_value=1901), patch.object(
                notifier.session, "post", return_value=self.response()) as send:
            notifier.deliver(pending)
        self.assertEqual(send.call_count, 1)
        self.assertIn("sctapi.ftqq.com", send.call_args.args[0])
        self.assertEqual(pending, [])

    def test_send_interval(self):
        pending = [event("change", "first"), event("change", "second")]
        with patch("notifications.time.time", return_value=1000), patch.object(
                self.notifier.session, "post", return_value=self.response()) as send:
            self.notifier.deliver(pending)
        self.assertEqual(send.call_count, 1)
        self.assertEqual(len(pending), 1)

    def test_key_environment_precedence_and_wrong_product(self):
        with patch.dict(os.environ, {"TEST_WECHAT_KEY": "SCTENVONLY"}):
            self.assertEqual(self.notifier.sendkey(self.config["notifications"]["serverchan"]), "SCTENVONLY")
        with patch.dict(os.environ, {"TEST_WECHAT_KEY": "sctp123tOTHER"}):
            with self.assertRaises(MonitorError):
                self.notifier.validate()

    def test_configure_preserves_user_settings_without_sending(self):
        path = self.base / "config.json"
        atomic_json(path, {"state_file": "state.json", "filters": {"models": ["A40"]},
                           "notifications": {"webhook": {"enabled": False}}})
        with patch("requests.Session.post") as send:
            configure(path, self.key)
        send.assert_not_called()
        saved = read_json(path)
        self.assertEqual(saved["filters"]["models"], ["A40"])
        self.assertTrue(saved["notifications"]["notify_startup"])
        self.assertTrue(saved["notifications"]["serverchan"]["enabled"])
        self.assertNotIn(self.key, path.read_text())
        self.assertEqual(read_json(self.base / ".secrets/serverchan.json")["sendkey"], self.key)

    def test_notification_test_does_not_query_cloud(self):
        path = self.base / "config.json"
        atomic_json(path, self.config)
        with patch("notifications.requests.Session.post", return_value=self.response()) as send:
            self.assertEqual(notification_test(path), 0)
        self.assertEqual(send.call_count, 1)
        self.assertFalse((self.base / ".state").exists())

    def test_startup_only_after_success_including_zero_free(self):
        root = Path(__file__).resolve().parents[1]
        c = read_json(root / "config.private.example.json")
        c["notifications"] = {"notify_startup": True}
        path = self.base / "config.json"
        atomic_json(path, c)
        calls = []
        def delivery(pending):
            calls.extend(copy.deepcopy(pending))
            pending.clear()
        row = {"machine_id": "a", "machine_type": "gpu", "gpu_name": "A40", "gpu": {"idle": 0, "total": 8}}
        with patch("monitor.ApiSource.fetch", side_effect=[MonitorError("auth", "expired"), [row], [row]]), \
             patch("monitor.Notifier.deliver", side_effect=delivery), \
             patch("monitor.time.sleep", side_effect=[None, None, KeyboardInterrupt]), redirect_stdout(io.StringIO()):
            with self.assertRaises(KeyboardInterrupt):
                run(path)
        self.assertEqual([ev["type"] for ev in calls], ["monitor_error", "recovered", "monitor_started"])


if __name__ == "__main__":
    unittest.main()
