# 自有微信公众号通知

`wechat_official` 通过微信官方模板消息接口发送，无需 Server酱。前提是账号有模板消息接口权限、模板适合 GPU 资源提醒，且接收者已关注。能注册或登录公众号，不代表拥有消息接口权限；以该账号后台的权限、模板库、额度和使用规则为准。

## 账号和模板

可先用 [微信公众平台接口测试号](https://mp.weixin.qq.com/debug/cgi-bin/sandboxinfo?action=showinfo&t=sandbox/index) 验证。测试号后台目前显示最多 20 个关注者、10 个测试模板；它用于开发测试，不能据此承诺正式服务的权限或容量。正式号需要自己的 AppID、接收者 OpenID、模板 ID 和获准的模板字段。

在测试号后台新建模板，标题为 `GPU 资源状态提醒`，内容为：

```text
事件：{{title.DATA}}
详情：{{message.DATA}}
时间：{{time.DATA}}
```

在 `notifications` 中添加以下配置。此 `data` 仅适用于上面的测试模板，正式模板请替换成后台实际字段：

```json
"wechat_official": {
  "enabled": true,
  "credentials_file": ".secrets/wechat-official.json",
  "token_cache_file": ".state/wechat-access-token.json",
  "timeout_seconds": 10,
  "min_interval_seconds": 60,
  "retry_seconds": 900,
  "data": {
    "title": {"value": "{{title}}"},
    "message": {"value": "{{message}}"},
    "time": {"value": "{{time}}"}
  }
}
```

将 [凭据示例](../examples/wechat-official.credentials.json) 复制到 `.secrets/wechat-official.json`，填入自己的值或保留环境变量引用。四项分别来自公众号后台 AppID/AppSecret、已关注用户的 OpenID、模板列表中的模板 ID。不要将微信昵称、微信号或另一公众号的 OpenID 填入 `openid`。每个监控配置只向一个明确接收者发送，不会自动广播给关注者。

## 验证与迁移

运行 `python monitor.py --config config.json --notify-test` 验证。此命令向所有已启用通道发送；只测公众号时使用独立本地配置文件，仅启用 `wechat_official`。微信返回接受结果后，还需在手机确认送达。测试号成功不表示正式号已验证。迁移前先验证正式账号，再切换原通知配置。

消息字段支持 `{{id}}`、`{{type}}`、`{{time}}`、`{{message}}`、`{{title}}`。`title` 为消息首行（最多 32 字符），`time` 为 UTC 时间；模板字段有独立的类型和长度限制，需按所选模板配置，超限会返回失败，不会静默丢弃内容。可设置可选 `url` 作为 HTTPS 消息跳转链接，勿在链接中放入凭据。

## 常驻运行

访问令牌缓存在 `token_cache_file`，提前刷新；微信明确返回过期/无效令牌时最多刷新并重发一次。相同 AppID 的多个本机进程必须使用相同缓存文件，避免相互刷新旧接口令牌；不要同时从另一台机器或调试工具申请令牌。跨机器共用公众号时，应另建统一令牌与投递服务。缓存只给运行账号读写，不上传 Git。设置了 IP 白名单的账号需要添加实际服务器出口 IP。

使用仓库 systemd 服务时，将凭据放在 `/etc/auto-dl-private-monitor/`，缓存路径配置到 `/var/lib/auto-dl-private-monitor/`，确保运行账号可读凭据、可写缓存。不要放在服务保护的只读代码目录。

成功消息默认至少间隔 60 秒，失败默认 900 秒后重试，待发事件与重试时间持久化。与其他通道分别记录成功状态；一个通道重试不会重发另一通道已成功的事件。采用至少一次投递，网络超时等不确定结果可能导致重复消息，不能保证恰好一次。

本通道只进行出站 API 请求，无需开放服务器端口或提供回调 URL。当前工具不处理菜单、用户自助绑定、关注事件或送达回调；服务端返回接受仅代表请求成功。模板消息接口结构见 [腾讯云微信开放 API 文档](https://cloud.tencent.com/document/product/1301/126222)。
