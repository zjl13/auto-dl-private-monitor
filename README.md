# AutoDL 私有云 GPU 监控

[![Tests](https://github.com/zjl13/auto-dl-private-monitor/actions/workflows/tests.yml/badge.svg)](https://github.com/zjl13/auto-dl-private-monitor/actions/workflows/tests.yml)

监控 [AutoDL 私有云「所有主机」](https://private.autodl.com/console/machine) 的 GPU 空闲卡数与状态变化，支持独占、一卡多租、微信通知和自定义 JSON API。

- 按 GPU 型号、每台主机空闲数、同型号合计数量筛选。
- 一卡多租自动识别或显式开关；分别统计完全空闲与仍可分配的物理卡。
- 完整分页校验、登录失效识别、失败退避与持久化快照。
- 启动成功、资源变化、故障及恢复提醒；通知失败持久化重试。
- 浏览器登录采集、Cookie/Token、可配置登录流程及浏览器读取备选方案。

查询为只读操作。空闲数表示平台分配状态，不表示 GPU 利用率，也不保证满足 CPU、内存、配额等实际调度条件。私有云内部接口可能随部署版本变化，首次使用应核对页面与 `--dry-run` 结果。

## 安装与运行

需要 Python 3.10+。在项目目录执行：

```bash
python -m venv .venv
# Linux/macOS
source .venv/bin/activate
# Windows PowerShell 改用：.venv\Scripts\Activate.ps1

python -m pip install -r requirements-browser.txt
python -m playwright install chromium
```

复制 `config.private.example.json` 为本地 `config.json`，完成登录并核对数据：

```bash
python browser_login.py --config config.json
python monitor.py --config config.json --dry-run
python monitor.py --config config.json
```

登录窗口中选择目标租户并进入「所有主机」。终端提示捕获成功后按回车保存；认证头与浏览器状态写入已被 Git 忽略的 `.secrets/`。若默认 Chromium 无法启动，可在配置的 `browser` 中设置 `"channel": "msedge"` 或 `"chrome"`，使用已安装的对应浏览器。

已有有效会话的服务器只需安装 `requirements.txt`；浏览器依赖仅用于登录采集或浏览器数据源。无图形界面环境可从可信桌面安全传入会话文件，但设备/IP 绑定可能限制复用。

| 命令选项 | 行为 |
| --- | --- |
| 无附加选项 | 持续轮询，Ctrl+C 停止 |
| `--dry-run` | 实际查询一次并输出结果，不写状态、不通知 |
| `--once` | 完成一轮查询、状态保存和变化提醒，不发启动通知 |
| `--notify-test` | 向已启用通道发送测试消息，不查询 GPU |
| `--sample examples/sample.private.json` | 解析离线样例，不联网 |

退出码：`0` 成功；`1` 采集或通知未完成；`2` 配置或运行环境错误。

## RTX 4090 配置

替换 `config.json` 中的 `filters`，其余配置保留：

```json
"filters": {
  "models": ["\\bRTX\\s*4090\\b"],
  "model_match": "regex",
  "regions": [],
  "only_free": true,
  "min_free_per_resource": 1,
  "min_total_free_per_model": 1,
  "allowed_statuses": []
}
```

该规则匹配 RTX 4090，排除 RTX 4090D。要求同一台主机至少 2 张卡时，将两个数量阈值均设为 `2`。`models: []` 匹配所有型号；`contains`、`exact`、`regex` 均忽略大小写。

轮询默认 60 秒，附加最多 10% 正向随机延迟；在 `poll.interval_seconds` 调整。失败采用指数退避，并遵循服务端 `Retry-After`。

## 一卡多租

在 `availability` 中设置 `sharing` 和 `free_definition`：

| `sharing` | 行为 |
| --- | --- |
| `auto` | 默认。逐主机识别 `gpu_max_instance_num`，大于 1 时查询逐卡占用 |
| `disabled` | 按非多租处理；若后端报告已开启多租，报配置不一致 |
| `enabled` | 强制逐卡查询，需要查看占用权限 |

| `free_definition` | 多租主机空闲口径 |
| --- | --- |
| `exclusive` | 默认。未占用满，且实例绑定为空，表示整卡完全空闲 |
| `allocatable` | 未占用满，允许已有实例，表示仍可分配的共享卡 |

计数单位始终是物理卡张数。例如一张全空、一张部分占用、一张占满：`exclusive` 为 1，`allocatable` 为 2。普通主机直接读取 `gpu.idle/gpu.total`。缺少绑定字段、权限不足或逐卡查询失败时，整轮不更新快照。

## 微信通知

使用 [Server酱 Turbo](https://sct.ftqq.com) 的 SCT SendKey，并在其控制台绑定微信通道：

```bash
python setup_wechat.py --config config.json
python monitor.py --config config.json --notify-test
python monitor.py --config config.json
```

配置工具将密钥保存到本机 `.secrets/serverchan.json`，并开启微信及启动通知。第一次完整资源查询成功后发送启动消息，即使空闲数为 0；此后只在资源变化、故障或恢复时提醒。无变化时保持安静。

环境变量 `SERVERCHAN_SENDKEY` 优先于密钥文件。服务接受消息不等于手机已送达；通道、额度和频率以 Server酱控制台为准。详细参数见 [通知配置](docs/WECHAT.md)。

## 接口与配置

| 示例文件 | 用途 |
| --- | --- |
| `config.private.example.json` | AutoDL 私有云 API，默认不发送外部通知 |
| `config.wechat.example.json` | 私有云 API，启用微信及启动提醒，需另外配置密钥 |
| `config.generic.example.json` | 自定义 JSON API、字段映射与分页 |
| `config.dom.example.json` | 已确认单页且未开启多租时的 DOM 读取 |

默认主机接口为 `POST /api/v2/machine/list`，使用 `page_index/page_size` 分页；多租逐卡接口为 `POST /api/v2/gpu_stock/list`。这些是页面使用的内部接口，不是稳定公开 API。

接口发现、认证、字段映射、分页和浏览器备选方案见 [配置参考](docs/CONFIGURATION.md)。

## 运行与维护

需要电脑关机后继续监控时，可部署到常在线服务器，使用仓库提供的 systemd 服务实现开机启动和进程自动恢复，见 [Linux 常驻部署](docs/DEPLOYMENT.md)。

状态位于 `state_file`，默认 `.state/private-machine.json`。完整查询失败时保留上次快照；相同结果不重复提醒。快照保留零空闲记录，因此能识别「有卡变无卡」。每个状态文件只允许一个运行实例。

长期运行可交给操作系统进程管理器；使用定时任务时调用 `--once` 并禁止重叠执行。重新采集认证头后，API 模式会在后续请求读取新凭据。修改筛选条件、共享口径等配置后重启；存在待发事件时，应先完成投递或为新范围配置独立 `state_file`。

不要提交 `config.json`、`.secrets/`、`.state/`、HAR 或真实响应。安全事项见 [SECURITY.md](SECURITY.md)，测试与贡献要求见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 许可与参考

[MIT License](LICENSE)。本项目独立实现；参考 [Jiayi-Fu/autodl-gpu-monitor](https://github.com/Jiayi-Fu/autodl-gpu-monitor) 的接口轮询与通知方式，以及 [wangzhao-desgin/autodl-gpu-monitor](https://github.com/wangzhao-desgin/autodl-gpu-monitor) 的浏览器会话与页面读取思路。
