import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests

from common import MonitorError, atomic_json
from monitor import event
from notifications import Notifier


class OfficialWechatTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.credentials = {"appid": "wxTEST", "appsecret": "SECRET_TEST_ONLY",
                            "openid": "SELF_TEST_ONLY", "template_id": "TEMPLATE_TEST_ONLY"}
        atomic_json(self.base / "credentials.json", self.credentials)
        self.settings = {"enabled": True, "credentials_file": "credentials.json",
                         "token_cache_file": ".state/token.json", "retry_seconds": 900,
                         "data": {"title": {"value": "{{title}}"}, "message": {"value": "{{message}}"},
                                  "time": {"value": "{{time}}"}}}
        self.config = {"auth": {"headers": {"Authorization": "CLOUD_SECRET"}},
                       "notifications": {"wechat_official": self.settings}}
        self.logs = []
        self.notifier = Notifier(self.config, self.base, self.logs.append)
        self.addCleanup(self.notifier.close)
        self.client = self.notifier.wechat

    @staticmethod
    def response(payload, status=200):
        response = Mock(status_code=status)
        response.json.return_value = payload
        return response

    def token(self, value="TOKEN_TEST_ONLY"):
        return self.response({"access_token": value, "expires_in": 7200})

    def accepted(self):
        return self.response({"errcode": 0, "msgid": 123})

    def test_send_fixed_host_recipient_template_and_isolated_auth(self):
        self.notifier.validate()
        pending = [event("notification_test", "测试通知\n详情")]
        with patch.object(self.client.session, "request", side_effect=[self.token(), self.accepted()]) as send:
            self.notifier.deliver(pending)
        self.assertFalse(pending)
        self.assertEqual(send.call_count, 2)
        args = send.call_args
        self.assertEqual(args.args, ("POST", "https://api.weixin.qq.com/cgi-bin/message/template/send"))
        self.assertEqual(args.kwargs["json"]["touser"], self.credentials["openid"])
        self.assertEqual(args.kwargs["json"]["data"]["title"]["value"], "测试通知")
        self.assertNotIn("CLOUD_SECRET", str(send.call_args_list))
        self.assertFalse(args.kwargs["allow_redirects"])
        self.assertNotIn("appsecret", args.kwargs["json"])

    def test_cached_token_shared_across_restarts_and_refreshes_before_expiry(self):
        with patch("wechat_official.time.time", return_value=1000), patch.object(
                self.client.session, "request", return_value=self.token()) as send:
            self.assertEqual(self.client.access_token(self.settings, self.credentials), "TOKEN_TEST_ONLY")
        self.assertEqual(send.call_count, 1)
        other = Notifier(self.config, self.base)
        self.addCleanup(other.close)
        with patch("wechat_official.time.time", return_value=8079), patch.object(other.wechat.session, "request") as send:
            self.assertEqual(other.wechat.access_token(self.settings, self.credentials), "TOKEN_TEST_ONLY")
        send.assert_not_called()
        with patch("wechat_official.time.time", return_value=8080), patch.object(
                other.wechat.session, "request", return_value=self.token("NEW_TOKEN")) as send:
            self.assertEqual(other.wechat.access_token(self.settings, self.credentials), "NEW_TOKEN")
        self.assertEqual(send.call_count, 1)

    def test_expired_token_refresh_once_and_no_unbounded_send_retry(self):
        with patch.object(self.client.session, "request", side_effect=[
                self.token(), self.response({"errcode": 42001}), self.token("NEW_TOKEN"), self.accepted()]) as send:
            self.client.send(self.settings, {})
        self.assertEqual(send.call_count, 4)
        self.assertEqual(send.call_args.kwargs["params"]["access_token"], "NEW_TOKEN")
        with patch.object(self.client.session, "request", side_effect=[
                self.response({"errcode": 40014}), self.token("AGAIN"), self.response({"errcode": 40014})]) as send:
            with self.assertRaises(MonitorError):
                self.client.send(self.settings, {})
        self.assertEqual(send.call_count, 3)

    def test_rotation_invalidates_cache_without_persisting_secret(self):
        with patch.object(self.client.session, "request", return_value=self.token()):
            self.client.access_token(self.settings, self.credentials)
        changed = dict(self.credentials, appsecret="ROTATED_SECRET_TEST_ONLY")
        atomic_json(self.base / "credentials.json", changed)
        with patch.object(self.client.session, "request", side_effect=[self.token("ROTATED"), self.accepted()]) as send:
            self.client.send(self.settings, {})
        self.assertEqual(send.call_count, 2)
        cache = (self.base / ".state/token.json").read_text()
        self.assertNotIn(changed["appsecret"], cache)
        self.assertNotIn(changed["openid"], cache)

    def test_non_success_response_never_marks_delivered(self):
        for payload in ({"errcode": False}, {"errcode": 0}, {"msgid": 10}, {"errcode": 0, "msgid": None},
                        {"errcode": "0", "msgid": 10}, {"errcode": 48001}, []):
            with self.subTest(payload=payload), patch.object(self.client, "access_token", return_value="TOKEN"), \
                    patch.object(self.client.session, "request", return_value=self.response(payload)):
                with self.assertRaises(MonitorError):
                    self.client.send(self.settings, {})

    def test_network_error_is_sanitized_and_backoff_survives_restart(self):
        pending = [event("change", "测试")]
        with patch("notifications.time.time", return_value=1000), patch.object(self.client.session, "request",
                side_effect=requests.ConnectionError("SECRET_TEST_ONLY TOKEN_TEST_ONLY")):
            self.notifier.deliver(pending)
        self.assertEqual(pending[0]["_retry_at"]["wechat_official"], 1900)
        self.assertNotIn("SECRET_TEST_ONLY", str(pending) + str(self.logs))
        self.assertNotIn("TOKEN_TEST_ONLY", str(pending) + str(self.logs))
        other = Notifier(self.config, self.base)
        self.addCleanup(other.close)
        restored = copy.deepcopy(pending)
        with patch("notifications.time.time", return_value=1899), patch.object(other.wechat.session, "request") as send:
            other.deliver(restored)
        send.assert_not_called()
        with patch("notifications.time.time", return_value=1901), patch.object(
                other.wechat.session, "request", side_effect=[self.token(), self.accepted()]):
            other.deliver(restored)
        self.assertFalse(restored)

    def test_failure_in_other_channel_does_not_resend_official_message(self):
        self.config["notifications"]["webhook"] = {"enabled": True, "url": "https://example.invalid"}
        notifier = Notifier(self.config, self.base)
        self.addCleanup(notifier.close)
        pending = [event("change", "测试")]
        with patch.object(notifier.session, "post", side_effect=requests.ConnectionError()), patch.object(
                notifier.wechat.session, "request", side_effect=[self.token(), self.accepted()]):
            notifier.deliver(pending)
        self.assertEqual(pending[0]["_delivered"], ["wechat_official"])
        with patch.object(notifier.session, "post", return_value=self.response({})), patch.object(
                notifier.wechat.session, "request") as send:
            notifier.deliver(pending)
        send.assert_not_called()
        self.assertFalse(pending)

    def test_missing_recipient_fails_before_network(self):
        del self.credentials["openid"]
        atomic_json(self.base / "credentials.json", self.credentials)
        with patch.object(self.client.session, "request") as send, self.assertRaises(MonitorError):
            self.notifier.validate()
        send.assert_not_called()

    def test_cache_never_overwrites_credentials(self):
        self.settings["token_cache_file"] = "credentials.json"
        before = (self.base / "credentials.json").read_bytes()
        with patch.object(self.client.session, "request") as send, self.assertRaises(MonitorError):
            self.client.access_token(self.settings, self.credentials)
        send.assert_not_called()
        self.assertEqual((self.base / "credentials.json").read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
