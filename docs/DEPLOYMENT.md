# Linux 常驻部署

使用持续在线、能够访问私有云与通知服务的 Linux 服务器。API 模式不需要 GPU 或浏览器。以下路径与仓库的 systemd 单元保持一致，适用于 Ubuntu/Debian。

## 安装

```bash
sudo apt-get update
sudo apt-get install -y git python3-venv
sudo git clone https://github.com/zjl13/auto-dl-private-monitor.git /opt/auto-dl-private-monitor
sudo python3 -m venv /opt/auto-dl-private-monitor/.venv
sudo /opt/auto-dl-private-monitor/.venv/bin/python -m pip install -r /opt/auto-dl-private-monitor/requirements.txt

sudo useradd --system --user-group --home-dir /var/lib/auto-dl-private-monitor --no-create-home --shell /usr/sbin/nologin autodl-monitor
sudo install -d -o root -g autodl-monitor -m 0750 /etc/auto-dl-private-monitor
sudo install -d -o autodl-monitor -g autodl-monitor -m 0700 /var/lib/auto-dl-private-monitor
```

应用和虚拟环境由 root 管理，服务使用独立账号，仅向状态目录写入。已有同名账号或安装目录时，先核对其用途，再更新部署。

## 配置与凭据

在可信桌面通过 `browser_login.py` 完成登录，再用 SSH/SCP 安全传输以下文件。只需 API 认证头，不需要上传整个浏览器会话。

| 本机文件 | 服务器路径 |
| --- | --- |
| `config.json` | `/etc/auto-dl-private-monitor/config.json` |
| `.secrets/credentials.json` | `/etc/auto-dl-private-monitor/credentials.json` |
| `.secrets/serverchan.json`（启用微信时） | `/etc/auto-dl-private-monitor/serverchan.json` |

将服务器配置中的路径调整为：

| 配置项 | 值 |
| --- | --- |
| `source` | `api` |
| `state_file` | `/var/lib/auto-dl-private-monitor/state.json` |
| `auth.credentials_file` | `/etc/auto-dl-private-monitor/credentials.json` |
| `notifications.serverchan.sendkey_file` | `/etc/auto-dl-private-monitor/serverchan.json` |

保留原有接口、筛选与通知参数。凭据文件不应放入 `/opt` 中的 Git 工作目录。

```bash
sudo chown root:autodl-monitor /etc/auto-dl-private-monitor/*.json
sudo chmod 0640 /etc/auto-dl-private-monitor/*.json
sudo -u autodl-monitor /opt/auto-dl-private-monitor/.venv/bin/python /opt/auto-dl-private-monitor/monitor.py --config /etc/auto-dl-private-monitor/config.json --dry-run
```

首次先确认会话可从服务器出口复用，并核对卡数。若需要保留原监控基线和待发提醒，将旧 `state_file` 复制到服务器配置的状态路径，所有者设为 `autodl-monitor:autodl-monitor`、权限设为 `0600`；不要复制 `.lock` 文件。改变筛选范围等配置可能需要新基线。

## 安装服务

```bash
sudo install -m 0644 /opt/auto-dl-private-monitor/deploy/auto-dl-private-monitor.service /etc/systemd/system/
sudo systemd-analyze verify /etc/systemd/system/auto-dl-private-monitor.service
sudo systemctl daemon-reload
sudo systemctl enable --now auto-dl-private-monitor
sudo systemctl status auto-dl-private-monitor --no-pager
```

服务随服务器启动，进程异常退出后约 30 秒重新启动。网络和接口故障由脚本内部退避重试，不需要每次重启服务。首次成功查询会按 `notify_startup` 发送启动通知，使用服务端额度。

迁移时先验证服务器查询与通知成功，再停止原设备上的监控；确认服务器连续轮询且没有待发错误。迁移完成后只保留一个监控实例。

## 管理

```bash
# 状态与日志
sudo systemctl status auto-dl-private-monitor --no-pager
sudo journalctl -u auto-dl-private-monitor -n 30 -f

# 停止 / 开启 / 重启
sudo systemctl stop auto-dl-private-monitor
sudo systemctl start auto-dl-private-monitor
sudo systemctl restart auto-dl-private-monitor

# 停止并取消开机启动
sudo systemctl disable --now auto-dl-private-monitor
# 恢复开机启动并立即运行
sudo systemctl enable --now auto-dl-private-monitor
```

按 Ctrl+C 只退出日志跟踪。`stop` 后本次运行停止，但仍保留开机启动设置；长期停用使用 `disable --now`。

API 会话过期时，在可信桌面重新登录，将新的认证头文件安全替换到服务器原路径，并保持权限。脚本后续请求会重新读取该文件。修改配置本身后需要重启服务。

配置更新与程序升级前先停止服务，保留私有配置和状态备份。重启后检查成功查询时间，而不只看进程是否存在。systemd 能恢复退出的进程，服务器断电、失去网络或接口登录失效仍会中断监控。
