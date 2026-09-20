# 微信通知：Server酱 Turbo

从 0.2.0 起直接支持 Server酱 Turbo，无需自行搭建中转。你在它的控制台绑定微信，脚本通过 HTTPS 发送启动成功、资源变化、监控异常、恢复和独立测试通知。

## 配置一次，以后正常启动即可

1. 打开 [Server酱 Turbo](https://sct.ftqq.com)，用微信扫码登录，按控制台说明设置微信消息通道，复制 **SCT 开头**的 SendKey。
2. 在项目目录运行配置工具并粘贴 SendKey，输入不会显示；只保存到本机 `.secrets/serverchan.json`。若 `config.json` 不存在，会基于私有云示例创建；已有 GPU/接口设置会保留。配置前请先停止监控进程。
3. 发送测试消息，在手机微信中确认收到。
4. 配好私有云登录会话后，正常启动监控。

Windows PowerShell（已按 README 安装到 `.venv`）：

```powershell
.venv\Scripts\python.exe setup_wechat.py --config config.json
.venv\Scripts\python.exe monitor.py --config config.json --notify-test

# 尚未配置私有云登录时执行；已有有效会话则跳过
.venv\Scripts\python.exe browser_login.py --config config.json

.venv\Scripts\python.exe monitor.py --config config.json
```

Linux/macOS（激活虚拟环境后，云端会话配置见 README）：

```bash
python setup_wechat.py --config config.json
python monitor.py --config config.json --notify-test
python monitor.py --config config.json
```

API 轮询及微信通知依赖仍只有 Requests；浏览器登录才需要可选浏览器依赖。

**测试通知不需要云端 Token，不查询 GPU、不读取云端会话、不修改监控状态。** 它会发给所有已启用通道；失败退出 1，不自动重试测试消息。日志“服务已接受”之后，仍需在手机中确认送达。

Turbo 可走微信服务号/企业微信等；Server酱³ 的 `sctp` Key 用于独立 App。本模块只接受 Turbo 的 SCT Key。接收普通微信通知请选择微信通道，不要误选企业微信群机器人。[官方通道说明](https://sct.ftqq.com/docs/getting-started/channels/)

## 启动与告警行为

- 配置工具打开 `notifications.notify_startup: true`。
- 长期监控取得第一份完整、成功的资源快照后，发送“GPU 监控已启动，首次资源查询成功”，即使空闲卡数为 0。
- 初次查询登录失败时发送故障提醒；不会把进程启动等同于监控正常。恢复成功后会发送恢复和启动消息。
- 每个进程生命周期创建一次启动事件。启动消息含首次可用资源摘要，避免同时再发相同的首次可用提醒。
- 后续数量/状态变化及故障恢复沿用原去重逻辑；无变化时不按轮询周期发消息。
- `--once` 不创建启动事件，避免计划任务刷屏，但仍按变化规则提醒。`--dry-run`、`--sample` 不发送网络通知。

## 手工配置与环境变量

可复制 `config.wechat.example.json`，或在已有 `notifications` 中增加：

```json
"notify_startup": true,
"serverchan": {
  "enabled": true,
  "sendkey_env": "SERVERCHAN_SENDKEY",
  "sendkey_file": ".secrets/serverchan.json",
  "channel": "",
  "timeout_seconds": 10,
  "min_interval_seconds": 60,
  "retry_seconds": 900
}
```

环境变量 `SERVERCHAN_SENDKEY` 优先于密钥文件。使用环境变量时可以不运行配置工具，但要启用上述配置。文件格式为 `{"sendkey":"你的 SCT Key"}`，路径相对配置文件所在目录，每次发送都会重新读取。

`channel` 留空使用 Server酱控制台默认通道；需要覆盖时填写控制台提供的值，不猜编号。关闭微信通知设置 `serverchan.enabled: false`；只关闭启动提醒设置 `notify_startup: false`。更改配置后重启。

## 重试、额度与隐私

- 调用 `POST https://sctapi.ftqq.com/{SendKey}.send`，用表单传 `title/desp`，要求 HTTP 2xx 且 JSON `code` 严格为整数 0。HTTP 200 但业务失败不会算成功。[官方接入说明](https://sct.ftqq.com/docs/integrations/java/)
- 默认同一监控进程中，Server酱请求成功后至少间隔 60 秒；失败事件至少等 900 秒再试。失败重试时间写入状态文件，重启后保留。实际重试时间还受轮询周期影响；它不是独立的即时投递线程。
- webhook 和微信分别记录成功结果。一方重试时不会重发另一方已成功的事件。停用通道后不再等它的旧事件投递；新启用的通道也会收到当前仍待发的事件。
- 远端接受但本机尚未保存就退出，仍可能重复，属于“至少一次”投递。其他程序也会消耗同一账号额度；本脚本无法核算全账号余量。
- 截至 2026-09-20，官方说明列出免费版每天 5 条及频率限制；启动、测试和告警均占用额度，以控制台规则为准。[官方额度说明](https://sct.ftqq.com/docs/getting-started/channels/)
- 标题/正文的显示能力取决于通道和账户。脚本发送资源信息和事件编号，**不会发送私有云 Cookie/Authorization**。资源信息会经过 Server酱，其保留政策由该服务决定。
- 不要把 SendKey 发到聊天、公开 Issue 或 Git；`.secrets/` 已忽略。泄漏后应在控制台重置，删除本地文件不能撤销密钥。

## 排错

| 现象 | 检查 |
| --- | --- |
| 未设置微信密钥 | 运行配置工具或设置环境变量；检查旧环境变量是否覆盖文件。 |
| sctp Key 被拒绝 | 改用 Turbo 的 SCT Key，设置微信通道。 |
| 服务接受，微信未收到 | 查看控制台发送日志、通道绑定、关注/屏蔽状态及额度。 |
| 暂未重试 | 默认失败等待 15 分钟，避免盲目反复测试。 |
| 没有启动成功通知 | 先独立测试微信，再检查云端登录；启动成功消息需要一次完整资源查询成功。 |

本版本已用模拟响应验证通知请求、业务失败、保密日志、多通道重试及启动行为。未使用你的 SendKey，尚未验证真实微信送达。
