# 通知配置

## Server酱 Turbo

在 [Server酱 Turbo](https://sct.ftqq.com) 配置微信接收通道后，运行：

```bash
python setup_wechat.py --config config.json
python monitor.py --config config.json --notify-test
```

配置工具保留已有接口与 GPU 筛选条件，写入本机密钥并启用启动提醒。修改配置前停止运行中的监控进程。支持 Turbo 的 SCT Key，不支持 Server酱³ 的 `sctp` Key。

手工配置时，在 `notifications` 中设置：

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

密钥文件格式为 `{"sendkey":"你的 SCT Key"}`；路径相对配置文件。环境变量优先，每次发送重新读取密钥文件。`channel` 留空使用服务端默认通道，覆盖值应来自控制台。

正常启动在首次完整资源查询成功后通知，包含当前资源摘要；初次失败会发送故障提醒，成功恢复后补发恢复和启动事件。`--once` 不产生启动事件；`--dry-run`、`--sample` 不发送通知。

服务请求使用 HTTPS POST 表单 `title/desp`，成功要求 HTTP 2xx 且 JSON `code` 为整数 `0`。日志表示服务已接受，手机送达还取决于通道绑定和额度。[官方接入说明](https://sct.ftqq.com/docs/integrations/java/)

## 自有微信公众号

支持使用自己的公众号直接调用微信模板消息接口。需要验证账号权限、模板和接收者绑定，见 [公众号直发配置](WECHAT_OFFICIAL.md)。此通道与 Server酱可独立启停，分别记录投递结果。

## 通用 webhook

启用 `notifications.webhook.enabled`，通过环境变量 `GPU_WEBHOOK_URL` 提供地址。默认发送 JSON：

```json
{"id":"事件ID","type":"事件类型","time":"UTC时间","message":"提醒内容"}
```

`template` 支持任意嵌套结构，替换 `{{id}}`、`{{type}}`、`{{time}}`、`{{message}}`。可通过 `success` 校验业务结果，例如 `{"path":"errcode","values":[0]}`；未配置时仅检查 HTTP 2xx。

## 投递行为

`notifications.change_mode` 默认 `all`，通知所有资源变化。设为 `increases_only` 时，只在符合筛选条件的同型号空闲卡合计增加、且当前满足可用条件时发送资源提醒；减少或数量不变时不发。每次成功查询仍更新基线，因此 `3 → 1 → 2` 只提醒最后一次增加。按型号分别比较，不同型号不相互抵消。启动、首次发现、故障和恢复通知独立于此开关；不需要首次发现提醒时设置 `notify_initial: false`。切换策略前应处理旧待发资源事件，避免继续发送旧策略排队的提醒。

- 资源数量、状态、进入或移出查询范围会触发变化事件；同类连续故障去重，恢复单独通知。
- 每个通道分别记录成功结果，避免另一通道重试时重复发送已成功消息。
- 微信成功请求默认至少间隔 60 秒；失败默认等待 900 秒再试，重试时间持久化。实际投递受轮询周期影响。
- webhook 失败在后续轮询重试。单轮最多检查 10 条待发事件，队列上限 1000 条。
- 使用「至少一次」投递：远端接受后本机未保存就退出，可能重复发送。接收方可按事件 `id` 去重。
- 启动、测试和告警都会消耗服务额度；额度与频率限制见 [官方通道说明](https://sct.ftqq.com/docs/getting-started/channels/)。

通知包含 GPU 型号、资源 ID、数量和事件编号。私有云认证信息不会转发到通知服务。SendKey、webhook 地址与本地状态均应按 [安全说明](../SECURITY.md) 保管。
