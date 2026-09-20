# 验证记录

日期：2026-09-20；版本：0.2.0。

本次本地环境：Windows，Python 3.12.10，Requests 2.34.2，Playwright 1.63.0，随 Playwright 安装的 Chromium。

`TEST_BROWSER=1 python -m unittest discover -s tests -v`：**31 项测试全部通过，无跳过**。

0.2.0 增加 10 项微信相关测试：原生表单与认证隔离、业务失败与跨重启退避、布尔假值不可当成功、日志不泄露 Key、多通道独立重试、发送间隔、环境变量优先级与 Key 类型、本机配置保留用户设置、测试通知不查询云端、启动消息仅在查询成功后发送。

覆盖：非多租、全空/部分占用/占满共享卡、两种计数定义、开关与实际容量冲突、旧版绑定字段、缺失字段/重复卡、CPU 排除、型号/数量阈值、数量变化与恢复、单进程锁、HTTP 及业务鉴权失败、页码分页完整性、登录重试、凭据热更新与域名绑定、webhook 凭据隔离/重试、重启后状态保留、本地 Chromium 网络响应与 DOM 读取。

另外已运行主配置的 `--sample examples/sample.private.json`：解析出两个 GPU 主机，排除 CPU 主机；合格的演示 RTX 4090 空闲数为 2。

GitHub Actions 已验证通过：Ubuntu/Windows × Python 3.10、3.12、3.13 的 6 个核心任务，以及 Ubuntu 上的 Chromium 浏览器任务，共 7 个任务全部成功。[首次公开仓库验证记录](https://github.com/zjl13/auto-dl-private-monitor/actions/runs/35507184049)，对应代码提交 `546e0b664d564a2f780ca1792b0b7e38649a60ee`。核心任务跳过可选浏览器测试，浏览器任务运行全部 31 项测试。

尚未执行真实私有云账号登录/资源查询和实际外部 webhook/微信投递。交互式登录采集工具也尚未用实际 SSO 账号验证。测试通过不替代部署后的 `--dry-run` 核对。
