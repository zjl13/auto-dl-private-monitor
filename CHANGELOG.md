# Changelog

## Unreleased

- 新增自有微信公众号模板消息通道，支持共享令牌缓存、到期刷新、独立投递状态与失败重试。
- 提供独立服务账号、受限目录权限和开机启动的 Linux systemd 部署配置。
- 浏览器登录与读取支持通过 `browser.channel` 选择已安装的 Edge 或 Chrome。
- 精简文档，集中提供运行说明、接口配置参考与通知配置。

## 0.2.0 — 2026-09-20

- Server酱 Turbo 微信通知，支持独立密钥文件和环境变量。
- 新增 `setup_wechat.py`、`--notify-test` 和首次查询成功后的启动通知。
- 多通道独立记录投递结果；微信失败延迟重试并持久化重试时间。

## 0.1.0 — 2026-09-20

- AutoDL 私有云 API、通用 JSON API、人工登录捕获和浏览器读取。
- 一卡多租 `auto/disabled/enabled`，物理卡 `exclusive/allocatable` 两种计数方式。
- GPU 筛选、完整分页校验、会话失效处理、通知与状态持久化、单进程锁。
