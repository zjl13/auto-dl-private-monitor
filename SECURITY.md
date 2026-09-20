# 安全与隐私

- Cookie、Authorization、SSO ticket、浏览器 storage state 与 webhook URL 都是凭据。只放在本机环境变量或 `.secrets/`，不放在公开 Issue、日志、截图、HAR 或 Git 历史中。
- `.state/` 含资源 ID、型号及变化记录；虽然不保存认证头，也不要公开。
- 使用仅能查询目标租户资源的账号。脚本只发配置中的资源查询与可选登录请求；不要把创建、删除、关机、开机或租户切换接口填成查询接口。
- 默认校验 HTTPS 证书、不跟随 API 重定向，查询与 webhook 使用独立会话。内部 CA 用 `api.ca_bundle` 指定证书包；不要关闭验证。
- 默认不读取系统代理或 `.netrc`；如需代理，在确认网络环境后设置对应 `trust_env: true`。
- Linux/macOS 用 `chmod 700 .secrets .state` 和 `chmod 600 .secrets/* .state/*`；Windows 为项目目录设置只允许自己的账户访问的 ACL。代码创建的临时凭据文件在 POSIX 上权限为 0600；Windows 继承所在目录 ACL。
- 发到外部 webhook 的内容包含 GPU 型号、资源 ID 和数量。需要隐私时使用自己管理的通知服务。
- Server酱 SendKey 也是凭据，只保存在 `.secrets/serverchan.json` 或环境变量。微信消息中的资源信息会经由 Server酱处理；通知会话与私有云会话隔离，不转发云端认证头。
- 发现凭据泄漏应立即撤销或轮换凭据，再清理历史；仅删除当前文件不能撤销已泄漏的会话。

报告问题时提供脱敏字段结构、Python 版本、脚本版本、错误类别及复现步骤。安全问题优先使用仓库的私密安全报告渠道（仓库维护者需自行启用）；不要在公开 Issue 中上传可利用的凭据。
