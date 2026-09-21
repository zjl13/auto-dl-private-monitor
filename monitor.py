#!/usr/bin/env python3
"""Configurable private AutoDL GPU availability monitor (no purchase/start/stop code)."""
import argparse
import hashlib
import json
import random
import re
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from common import (MonitorError, StateLock, atomic_json, get_path, normalize,
                    read_json, select_snapshot, validate_payload)
from sources import ApiSource, BrowserSource
from availability import adapt_private
from notifications import Notifier


def log(message):
    print(f"[{datetime.now().astimezone().isoformat(timespec='seconds')}] {message}", flush=True)


def event(kind, message):
    return {"id": str(uuid.uuid4()), "type": kind,
            "time": datetime.now(timezone.utc).isoformat(), "message": message}


def snapshot_text(snapshot):
    counts = json.dumps(snapshot["free_by_model"], ensure_ascii=False)
    lines = [f"满足条件={snapshot['available']}；合格资源={len(snapshot['eligible'])}；各型号空闲卡数={counts}"]
    for row in sorted(snapshot["eligible"].values(), key=lambda r: r["id"])[:30]:
        lines.append(f"{row['id']} | {row['model']} | 空闲 {row['free']}/{row['total']} | {row['status']} | {row['region']}")
    if len(snapshot["eligible"]) > 30:
        lines.append("其余资源省略；完整结果保存在本地状态文件。")
    return "\n".join(lines)


def update_success(state, snapshot, notify_initial=True, change_mode="all"):
    events = []
    if state.get("error"):
        events.append(event("recovered", "GPU 监控恢复，已重新取得完整资源快照。"))
    previous = state.get("snapshot")
    if previous is None:
        if notify_initial and snapshot["available"]:
            events.append(event("initial_available", "首次检测到可用 GPU\n" + snapshot_text(snapshot)))
    elif change_mode == "increases_only":
        increases = {model: (previous["free_by_model"].get(model, 0), count)
                     for model, count in snapshot["free_by_model"].items()
                     if count > previous["free_by_model"].get(model, 0)}
        if increases and snapshot["available"]:
            details = "\n".join(f"{model}: 空闲 {before} → {after}"
                                for model, (before, after) in sorted(increases.items()))
            events.append(event("gpu_increase", "GPU 空闲数量增加\n" + details + "\n" + snapshot_text(snapshot)))
    elif previous != snapshot:
        before, after = previous["resources"], snapshot["resources"]
        added, removed = sorted(after.keys() - before.keys()), sorted(before.keys() - after.keys())
        changed = sorted(k for k in before.keys() & after.keys() if before[k] != after[k])
        details = []
        for k in changed[:30]:
            details.append(f"{k}: 空闲 {before[k]['free']} → {after[k]['free']}, 状态 {before[k]['status']} → {after[k]['status']}")
        message = (f"GPU 资源状态变化；满足条件 {previous['available']} → {snapshot['available']}\n"
                   f"新增 {len(added)}，移出当前查询范围 {len(removed)}，变化 {len(changed)}\n"
                   + "\n".join(details) + "\n" + snapshot_text(snapshot))
        events.append(event("resource_change", message))
    state["snapshot"], state["error"] = snapshot, None
    return events


def update_failure(state, error):
    # Never replace the last good snapshot with [] on network/auth/schema failure.
    changed = state.get("error") != error.code
    state["error"] = error.code
    return [event("monitor_error", "GPU 监控异常：" + str(error))] if changed else []


def enqueue(state, events):
    if len(state["pending"]) + len(events) > 1000:
        raise MonitorError("outbox_full", "待发提醒超过 1000 条；请修复通知服务并检查状态文件。")
    for ev in events:
        log(ev["message"])
    state["pending"].extend(events)


def validate_config(config):
    if config.get("notifications", {}).get("change_mode", "all") not in ("all", "increases_only"):
        raise MonitorError("config", "notifications.change_mode 只支持 all/increases_only。")
    if config.get("source") not in ("api", "browser_network", "browser_dom"):
        raise MonitorError("config", "source 只支持 api/browser_network/browser_dom。")
    poll = config["poll"]
    if not isinstance(poll["interval_seconds"], (float, int)) or poll["interval_seconds"] < 1:
        raise MonitorError("config", "轮询周期至少为 1 秒；建议 30–60 秒。")
    if poll.get("max_backoff_seconds", 900) < poll["interval_seconds"]:
        raise MonitorError("config", "max_backoff_seconds 不能小于轮询周期。")
    if not 0 <= poll.get("jitter_fraction", 0.1) <= 0.5:
        raise MonitorError("config", "jitter_fraction 必须在 0 到 0.5 之间。")
    for name in ("min_free_per_resource", "min_total_free_per_model"):
        value = config.get("filters", {}).get(name, 1)
        if type(value) is not int or value < 0:
            raise MonitorError("config", f"{name} 必须为非负整数。")
    if config["mapping"].get("mode", "counts") not in ("counts", "cards"):
        raise MonitorError("config", "mapping.mode 只支持 counts/cards。")
    if config.get("filters", {}).get("model_match") == "regex":
        for pattern in config["filters"].get("models", []):
            re.compile(pattern)


def run(config_path, once=False, sample=None, dry_run=False):
    if sample or dry_run:
        return _run(config_path, once, sample, dry_run)
    path = Path(config_path).resolve()
    config = read_json(path)
    with StateLock(path.parent / config["state_file"]):
        return _run(path, once, sample, dry_run)


def _run(config_path, once=False, sample=None, dry_run=False):
    config_path = Path(config_path).resolve()
    config = read_json(config_path)
    validate_config(config)
    if sample:
        payload = read_json(sample)
        validate_payload(payload, config["api"].get("success"))
        items = adapt_private(get_path(payload, config["api"]["items_path"]), config)
        rows = normalize(items, config["mapping"])
        print(json.dumps(select_snapshot(rows, config.get("filters", {})), ensure_ascii=False, indent=2))
        return 0
    source = (ApiSource if config["source"] == "api" else BrowserSource)(config, config_path.parent)
    notifier = Notifier(config, config_path.parent, log)
    if not dry_run:
        notifier.validate()
    state_path = config_path.parent / config["state_file"]
    # Changed scope/filters creates a fresh baseline. Credentials are never written to state.
    scope = {k: config.get(k) for k in ("source", "api", "browser", "mapping", "filters", "availability")}
    scope_hash = hashlib.sha256(json.dumps(scope, sort_keys=True).encode()).hexdigest()
    state = read_json(state_path) if state_path.exists() and not dry_run else {}
    if not isinstance(state, dict) or (state and not isinstance(state.get("pending"), list)):
        raise MonitorError("state_format", "状态文件格式错误；请备份后检查。")
    if state.get("scope") != scope_hash:
        if state.get("pending"):
            raise MonitorError("state_scope", "配置范围变化且存在待发提醒；请为新范围配置另一个 state_file。")
        state = {"scope": scope_hash, "snapshot": None, "error": None, "pending": []}
    failures = 0
    startup_due = bool(config.get("notifications", {}).get("notify_startup", False)) and not once
    try:
        while True:
            retry_after, failed = 0, False
            try:
                rows = normalize(source.fetch(), config["mapping"])
                snapshot = select_snapshot(rows, config.get("filters", {}))
                log(f"读取 {len(rows)} 条资源，筛选范围 {len(snapshot['resources'])} 条，满足条件={snapshot['available']}")
                if dry_run:
                    print(json.dumps(snapshot, ensure_ascii=False, indent=2))
                    return 0
                events = update_success(state, snapshot,
                                        config.get("notifications", {}).get("notify_initial", True) and not startup_due,
                                        config.get("notifications", {}).get("change_mode", "all"))
                if startup_due:
                    events.append(event("monitor_started", "GPU 监控已启动，首次资源查询成功\n" + snapshot_text(snapshot)))
                    startup_due = False
                failures = 0
            except MonitorError as error:
                failed = True
                failures += 1
                retry_after = error.retry_after
                log(str(error))
                if dry_run:
                    return 1
                events = update_failure(state, error)
            enqueue(state, events)
            atomic_json(state_path, state)  # Persist event before attempted delivery.
            notifier.deliver(state["pending"])
            atomic_json(state_path, state)
            if once:
                return 1 if failed or state["pending"] else 0
            poll = config["poll"]
            base = poll["interval_seconds"]
            delay = min(poll.get("max_backoff_seconds", 900), base * 2 ** min(failures, 10))
            delay *= 1 + random.uniform(0, poll.get("jitter_fraction", 0.1))
            time.sleep(max(delay, retry_after))
    finally:
        source.close()
        notifier.close()


def notification_test(config_path):
    path = Path(config_path).resolve()
    notifier = Notifier(read_json(path), path.parent, log)
    try:
        if not notifier.channels:
            raise MonitorError("notifications_disabled", "没有启用通知通道；先运行 setup_wechat.py。")
        notifier.validate()
        pending = [event("notification_test", "GPU 监控通知测试\n这是一条测试消息，不包含云端凭据，也未查询 GPU 接口。")]
        notifier.deliver(pending)
        if pending:
            log("测试未全部成功；请检查通知服务设置。测试消息不会排队自动重试。")
            return 1
        log("通知服务已接受测试消息，请在微信或已配置的接收端确认收到。")
        return 0
    finally:
        notifier.close()


def main():
    parser = argparse.ArgumentParser(description="AutoDL 私有云 GPU 资源监控")
    parser.add_argument("--version", action="version", version="autodl-private-monitor 0.2.0")
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--once", action="store_true", help="仅执行一轮（保存状态并按配置提醒）")
    parser.add_argument("--dry-run", action="store_true", help="读取一次实际数据，输出标准化结果，不保存状态/发 webhook")
    parser.add_argument("--sample", help="使用本地 JSON 样本验证映射，不联网、不保存状态/发 webhook")
    parser.add_argument("--notify-test", action="store_true", help="只发一条通知测试，不查询私有云或写监控状态")
    args = parser.parse_args()
    if args.notify_test and (args.once or args.dry_run or args.sample):
        parser.error("--notify-test 不能与 --once/--dry-run/--sample 同用。")
    try:
        if args.notify_test:
            return notification_test(args.config)
        return run(args.config, args.once, args.sample, args.dry_run)
    except KeyboardInterrupt:
        log("已停止监控。")
        return 0
    except MonitorError as error:
        log(str(error))
        return 2
    except (KeyError, TypeError, ValueError, OSError, re.error):
        log("配置/文件格式错误；请对照示例和 README 检查必填项与文件权限。")
        return 2


if __name__ == "__main__":
    sys.exit(main())
