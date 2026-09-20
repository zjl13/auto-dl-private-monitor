# 贡献说明

欢迎提交接口适配、缺陷修复与测试。请用人工构造的响应复现问题，避免上传真实租户数据和凭据。

## 验证

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```

浏览器相关改动另需安装 `requirements-browser.txt` 和 Playwright Chromium，并设置 `TEST_BROWSER=1` 后运行同一测试命令。PowerShell 使用 `$env:TEST_BROWSER='1'`。

测试仅使用本机模拟服务和模拟响应，不需要 AutoDL 或通知服务凭据。CI 覆盖 Linux/Windows、Python 3.10/3.12/3.13 与 Chromium 集成。

## 适配约定

- 保持只读查询范围。
- 缺失字段不能静默当作零空闲。
- 分页或逐卡查询失败时丢弃整轮结果，保留上次完整快照。
- 对共享/非共享、空表、失效会话、部分分页和通知失败提供相应验证。
- 不记录认证头、含凭据的 URL 或完整异常响应。

贡献遵循仓库 [MIT License](LICENSE)，第三方依赖遵循其各自许可证。
