# 贡献说明

欢迎提交其他私有云版本的适配、分页支持和测试。

1. 安装 `requirements.txt`；浏览器相关改动再安装 `requirements-browser.txt` 和 Chromium。
2. 执行 `python -m unittest discover -s tests -v`。
3. 浏览器改动额外执行 README 中的 `TEST_BROWSER=1` 测试。
4. 用手工构造、无账号信息的 JSON 复现问题。共享/非共享、空表、失效会话、接口失败、部分分页应有对应验证。
5. 不提交 `.secrets/`、`.state/`、真实网络捕获或截图中的租户信息。配置样例只保留环境变量占位符。

接口的缺失字段不能静默当成 0；一个分页或逐卡查询失败时，应丢弃整轮快照。请保持只读监控范围。

首次发布前，维护者可将 LICENSE 的贡献者署名替换为自己希望使用的署名。项目未包含两个参考仓库的代码或 AutoDL 前端代码，参考分析列于 `docs/RESEARCH.md`。第三方库遵循其各自许可证。
