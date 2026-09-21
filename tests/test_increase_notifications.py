import copy
import unittest

from common import MonitorError
from monitor import update_failure, update_success, validate_config
from test_monitor import config, snapshot


class IncreaseNotificationTests(unittest.TestCase):
    def test_decrease_updates_baseline_then_increase_notifies(self):
        state = {"snapshot": snapshot(3), "error": None}
        self.assertEqual(update_success(state, snapshot(1), change_mode="increases_only"), [])
        self.assertEqual(state["snapshot"], snapshot(1))
        events = update_success(state, snapshot(2), change_mode="increases_only")
        self.assertEqual([e["type"] for e in events], ["gpu_increase"])
        self.assertIn("1 → 2", events[0]["message"])
        self.assertEqual(update_success(state, snapshot(2), change_mode="increases_only"), [])

    def test_zero_removed_and_metadata_do_not_notify(self):
        state = {"snapshot": snapshot(2)}
        changed = copy.deepcopy(snapshot(2))
        changed["resources"]["one"]["status"] = "different"
        self.assertEqual(update_success(state, changed, change_mode="increases_only"), [])
        self.assertEqual(update_success(state, snapshot(0), change_mode="increases_only"), [])
        empty = {"resources": {}, "eligible": {}, "free_by_model": {}, "available": False}
        self.assertEqual(update_success(state, empty, change_mode="increases_only"), [])
        self.assertEqual([e["type"] for e in update_success(state, snapshot(1), change_mode="increases_only")], ["gpu_increase"])

    def test_recovery_compares_last_successful_snapshot(self):
        state = {"snapshot": snapshot(2), "error": None}
        update_failure(state, MonitorError("network", "unavailable"))
        events = update_success(state, snapshot(1), change_mode="increases_only")
        self.assertEqual([e["type"] for e in events], ["recovered"])
        self.assertEqual(state["snapshot"], snapshot(1))

    def test_initial_and_default_policy_remain_configurable(self):
        self.assertEqual(update_success({}, snapshot(2), False, "increases_only"), [])
        self.assertEqual([e["type"] for e in update_success({"snapshot": snapshot(2)}, snapshot(1))], ["resource_change"])
        c = config()
        c.setdefault("notifications", {})["change_mode"] = "typo"
        with self.assertRaises(MonitorError):
            validate_config(c)
