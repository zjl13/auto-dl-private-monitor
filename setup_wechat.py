#!/usr/bin/env python3
"""Configure ServerChan Turbo locally, without echoing the SendKey or sending it."""
import argparse
import getpass
from pathlib import Path

from common import MonitorError, StateLock, atomic_json, read_json
from notifications import validate_sendkey


def configure(config_path, sendkey):
    sendkey = validate_sendkey(sendkey.strip())
    path = Path(config_path).resolve()
    config = read_json(path if path.exists() else Path(__file__).with_name("config.private.example.json"))
    with StateLock(path.parent / config["state_file"]):
        settings = config.setdefault("notifications", {})
        settings["notify_startup"] = True
        existing = settings.setdefault("serverchan", {})
        existing.update({"enabled": True, "sendkey_env": "SERVERCHAN_SENDKEY",
                         "sendkey_file": ".secrets/serverchan.json"})
        existing.setdefault("timeout_seconds", 10)
        existing.setdefault("min_interval_seconds", 60)
        existing.setdefault("retry_seconds", 900)
        atomic_json(path.parent / ".secrets/serverchan.json", {"sendkey": sendkey})
        atomic_json(path, config)


def main():
    parser = argparse.ArgumentParser(description="配置微信通知（Server酱 Turbo）")
    parser.add_argument("--config", default="config.json")
    args = parser.parse_args()
    print("先在 https://sct.ftqq.com 微信扫码登录，配置微信消息通道，复制 SCT 开头的 SendKey。")
    print("密钥仅保存到本机 .secrets/serverchan.json。此步骤不发消息。")
    try:
        key = getpass.getpass("粘贴 SendKey（输入不显示）：")
        configure(args.config, key)
        print("微信通知已配置。若设置了 SERVERCHAN_SENDKEY 环境变量，它会优先于本地文件。")
        print("下一步运行：python monitor.py --config <你的配置文件> --notify-test")
        return 0
    except (KeyboardInterrupt, EOFError):
        print("已取消。")
        return 1
    except MonitorError as error:
        print(str(error))
        return 2
    except (OSError, KeyError, TypeError, ValueError):
        print("配置失败；检查文件格式和目录访问权限。")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
