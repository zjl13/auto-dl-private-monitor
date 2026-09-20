# AutoDL 私有云 GPU 监控

**第一次使用：[完整使用教程](docs/USER_GUIDE_ZH.md)** — 按 Windows 的逐步命令完成安装、登录、卡数核对和微信通知，也包含 Linux/macOS 与排错说明。

监控私有云中的 GPU 空闲卡数、型号与状态变化，支持普通独占主机和一卡多租主机。默认适配 `https://private.autodl.com/console/machine` 的“所有主机”页面，也可以配置为其他私有云的内部 JSON 接口。

项目提供只读查询、控制台提醒和可选 webhook 提醒。不会购买实例、开关机或切换租户。

**微信通知（0.2.0）：** 已内置 Server酱 Turbo。运行 `setup_wechat.py` 在本机配置 SendKey，再用 `monitor.py --notify-test` 验证。配置后正常启动会在首次资源查询成功时发送通知，见 [微信通知配置](docs/WECHAT.md)。

**验证范围：** 私有云默认接口和字段来自 2026-09-20 对站点公开前端资源的静态分析；未使用真实账号验证后端响应。核心与浏览器链路用本地模拟服务验证。登录后请先运行 `--dry-run`，与页面逐项核对。没有公开 API 文档不代表没有前端接口，但这些内部接口可能随网站升级变化。依据及两个参考项目的分析见 [RESEARCH.md](docs/RESEARCH.md)。

## 功能

- 配置 API 地址、GET/POST、JSON/表单/查询参数、认证头、Cookie、CSRF、字段映射。
- 页码/游标分页；自动校验完整性，避免只查询第一页造成误报。
- Cookie/Token 环境变量、浏览器人工登录采集、可选多步 JSON 登录流程。
- 按型号、区域、每台机器空闲卡数、同型号合计数量及状态筛选。
- 多租自动识别、显式开关；区分“整卡完全空闲”和“仍可分配的共享卡”。
- 周期轮询、随机延迟、失败退避、429 Retry-After、401/403 与业务层登录失效识别。
- 持久化快照、变化去重、故障与恢复提醒、失败通知待发队列、原生微信推送及启动通知。
- 浏览器响应捕获和单页 DOM 读取备选方案。
- MIT 许可证、本地测试、GitHub Actions、凭据忽略规则。

## 快速开始：AutoDL 私有云

需要 Python 3.10+。下列命令均在解压后的项目目录执行。

### 1. 安装

Windows PowerShell：

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-browser.txt
.venv\Scripts\python.exe -m playwright install chromium
Copy-Item config.private.example.json config.json
```

Linux/macOS：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-browser.txt
python -m playwright install chromium
cp config.private.example.json config.json
```

Linux 无图形界面的服务器不适合进行人工登录。先在可信的桌面设备采集，再安全传输 `.secrets/credentials.json` 到服务器。服务器仅运行 API 模式时只需 `pip install -r requirements.txt`，不需要浏览器。会话若绑定设备/IP，传输后可能失效，应使用组织允许的登录方案。

### 2. 人工登录并采集认证头

Windows 将下文的 `python` 替换为 `.venv\Scripts\python.exe`；Linux/macOS 激活虚拟环境后直接运行。

```bash
python browser_login.py --config config.json --save-sample
```

在打开的浏览器中完成登录（包括扫码/验证码/SSO）、选择正确租户，进入“所有主机”。必要时刷新一次或切换分页。终端显示“已捕获一条成功的资源列表响应”后，回到终端按回车。

工具仅监听配置中指定的资源查询接口，保存：

| 本地文件 | 内容 |
| --- | --- |
| `.secrets/credentials.json` | 与 API 同源绑定的认证头，供 API 模式使用 |
| `.secrets/browser-state.json` | Cookie/localStorage/IndexedDB，供浏览器模式恢复会话 |
| `.secrets/captured-request.json` | 此次资源查询的方法、地址和请求体，供核对参数 |
| `.secrets/sample-response.json` | 指定 `--save-sample` 才保存的资源响应 |

这些文件含敏感信息，不要上传 GitHub。脚本不显示令牌，不要求将密码发给任何人。浏览器状态不包括 sessionStorage；依赖 sessionStorage 或设备绑定的站点可能需要额外适配。[Playwright 登录状态说明](https://playwright.dev/python/docs/auth)

### 3. 检查并开始轮询

```bash
# 离线演示：手工构造的示例，不会联网
python monitor.py --config config.private.example.json --sample examples/sample.private.json

# 读取实际数据一次，不发送 webhook，也不写监控状态
python monitor.py --config config.json --dry-run

# 长期运行；Ctrl+C 停止
python monitor.py --config config.json
```

主机显示“未开启”一卡多租时，应读取“空闲算力”列对应的数据。实际显示多少卡，以本次接口响应为准。

`--once` 执行一次正常监控，会保存状态并按配置提醒。退出码：0=成功；1=本轮采集或提醒未完成；2=配置/运行环境错误。`--dry-run` 和 `--sample` 用于核对数据，不发送通知。

## 一卡多租：开关与计数口径

修改 `config.json` 中的以下项即可；不要用这个片段替换整个 `availability` 对象，其余字段需保留：

```json
"availability": {
  "adapter": "autodl_private",
  "sharing": "auto",
  "free_definition": "exclusive"
}
```

| `sharing` | 行为 |
| --- | --- |
| `auto`（默认） | 每台主机读取 `gpu_max_instance_num`，大于 1 时走多租逐卡查询，否则使用主机列表空闲数。适合混合租户。 |
| `disabled` | 按未开启多租处理；若接口报告容量大于 1，会报配置不一致，避免用错口径。 |
| `enabled` | 对 GPU 主机强制执行逐卡查询，适合多租主机或需要逐卡确认的部署。 |

| `free_definition` | 多租主机的计数方式 |
| --- | --- |
| `exclusive`（默认） | `reserved=false` 且实例绑定为空：`gpu_bindings` 为空/null，并且旧版 `instance_uuid` 为空（若该字段存在）。 |
| `allocatable` | `reserved=false`：页面语义为“尚未占用满”，允许卡上已有其他租户实例。 |

**数量始终是物理卡张数，不是可租实例槽位数。** 假设 3 张卡中一张全空、一张部分占用、一张占满：`exclusive` 计 1 张；`allocatable` 计 2 张。不会拿 `gpu_max_instance_num × 总卡数` 当空闲卡数，也不会把部分占用卡算成独占空闲卡。

多租时向 `/api/v2/gpu_stock/list` 提交 `machine_id`，按 `gpu_uuid` 去重，读取 `reserved/gpu_bindings/instance_uuid`。两个绑定字段都不存在时，`exclusive` 模式报错；不会猜测空闲。默认前端抽屉一次读取全部卡，因此示例设置 `complete_list_confirmed: true`；其他版本若分页，需改适配或提供 `total_path` 完整性校验。

“查看占用”受租户权限控制。若没有权限，`enabled` 或自动识别出的共享主机无法可靠计数，会保留上次结果并发故障提醒。不要绕过权限；请管理员授予合法只读权限或提供授权接口。

这里监控的是平台记录的分配/预留状态，不测 GPU 利用率、显存使用率或真实进程。空闲卡也不保证一定能创建实例：CPU、内存、配额、排队策略和并发抢占仍可能影响调度。不同后端对 `reserved` 的定义应结合实际响应核对。

## GPU 筛选与提醒

例如关注 RTX 4090，要求同一台机器至少空闲 2 张：

```json
"filters": {
  "models": ["RTX 4090"],
  "model_match": "contains",
  "regions": [],
  "only_free": true,
  "min_free_per_resource": 2,
  "min_total_free_per_model": 2,
  "allowed_statuses": []
}
```

- `models: []` 匹配所有型号；多个型号为 OR。`contains/exact/regex` 都忽略大小写。需要区分 4090 与 4090D 时使用完整名称加 `exact` 或带边界的正则。
- `regions` 是区域字段的精确匹配；默认私有云页面没有映射区域，设置前应添加 `mapping.fields.region`。
- `min_free_per_resource` 对每个主机/资源池分别判断；不能把两台各 2 卡的主机当成一台 4 卡主机。
- `min_total_free_per_model` 汇总通过前述条件的同型号卡数；型号不同不会相加，名称不同的型号也不会自动归并。
- `only_free: false` 允许零空闲记录进入候选，但还需把 `min_free_per_resource` 设为 0；默认合计阈值仍要求至少 1 张才能报告满足条件。
- `allowed_statuses` 可限制 online/ready 等后端状态，需先映射 `status`。默认仅监控页面提供的空闲数。

为发现“2 张变成 0 张”，状态快照仍保留型号/区域匹配但未达到数量阈值的主机。因此数量、状态、新增、消失、共享模式变化都可能提醒；不是只提醒从 0 到有卡。退出查询范围的资源标记为“移出当前查询范围”，不宣称已被物理删除。

首次已有可用卡时默认提醒；设置 `notifications.notify_initial: false` 可仅建立基线。相同快照不重复提醒。网络/登录/结构错误不会清空快照；同类连续故障只发一次提醒，恢复后再提醒。

### Webhook

默认关闭网络提醒，仅输出控制台。设置 `notifications.webhook.enabled: true`，把 webhook 地址放入环境变量 `GPU_WEBHOOK_URL`。可以用本地可信中转服务转发到邮件、微信、飞书等。

直接接收微信通知可使用内置 `notifications.serverchan`，按 [微信通知配置](docs/WECHAT.md) 操作。配置工具启用微信和启动成功提醒，保留原来的 webhook 设置。

默认 JSON：`{"id":"事件ID","type":"事件类型","time":"UTC时间","message":"提醒内容"}`。`template` 可以任意嵌套，只替换 `{{id}}/{{type}}/{{time}}/{{message}}`。例如接受文本消息格式的服务可配置：

```json
"template": {"msgtype": "text", "text": {"content": "{{message}}"}},
"success": {"path": "errcode", "values": [0]}
```

这只是请求格式示例；以接收服务实际协议为准。若服务用 HTTP 200 返回业务失败，务必配置其成功字段 `success`。默认只检查 HTTP 2xx。

发送失败会保留待发事件；webhook 下轮重试，Server酱按配置延迟重试，单轮最多检查 10 条、队列最多 1000 条。网络通知是“至少一次”语义：服务器收到后连接中断、或写状态前进程退出，可能重复发送；接收方可按事件 `id` 去重。通知成功表示服务接受，不保证终端设备已送达。

## 不用浏览器也能配置登录

### 直接提供 Token / Cookie

用下面的 `auth` 替换原对象，不再保留 `credentials_file`：

```json
"auth": {
  "headers": {"Authorization": "${PRIVATE_GPU_TOKEN}"},
  "login": {"enabled": false}
}
```

该私有云前端把 localStorage 的 `token` 原样放入 `Authorization`，不自动加 `Bearer`。其他系统若要求 Bearer，就改为 `Bearer ${PRIVATE_GPU_TOKEN}`。以 Network 中实际请求为准。

安全输入 Token，避免直接进入命令历史：

```powershell
# Windows PowerShell
$secretToken = Read-Host 'Private GPU Token' -AsSecureString
$env:PRIVATE_GPU_TOKEN = [System.Net.NetworkCredential]::new('', $secretToken).Password
.venv\Scripts\python.exe monitor.py --config config.json --dry-run
```

```bash
# Bash
read -rsp 'Private GPU Token: ' PRIVATE_GPU_TOKEN; echo
export PRIVATE_GPU_TOKEN
python monitor.py --config config.json --dry-run
```

Cookie 认证改成 `"Cookie": "${PRIVATE_GPU_COOKIE}"`。额外租户头、Origin、Referer、CSRF 头可放入 `auth.headers`。不要把公有云 Token 直接假定为私有云会话。

可配置 `auth.csrf: {"cookie_name":"XSRF-TOKEN","header_name":"X-XSRF-TOKEN","url_decode":true}`，从登录 session Cookie 或显式 Cookie 头复制 CSRF 值。不同站点的 CSRF 机制可能需要专门适配。

凭据文件每轮请求重新读取；重新运行 `browser_login.py` 后监控可继续使用新会话。环境变量在进程启动时继承，修改外部环境变量后需重启脚本。凭据文件方式与 `auth.headers` 可同时使用，后者覆盖同名认证头。

### 可选多步 JSON 登录

`examples/auth.login.json` 展示 `账号密码 → ticket → token` 的可配置结构。把其内容替换到 `auth`，改为真实登录地址、参数及响应路径。单步登录可只保留一个 step；返回 Set-Cookie 的登录会自动保存在 Requests Session 中，可不配置令牌提取。

每步支持 `request`、`success` 和 `save`；例如 `save: {"LOGIN_TOKEN":"data.token"}` 后，可在认证头里引用 `${LOGIN_TOKEN}`。只有 `login.enabled: true` 才会主动登录。启动时登录，遇到 401/403 或配置的业务鉴权错误，每轮最多再登录一次，之后进入退避。

此模板**不宣称是 AutoDL 私有云的密码登录接口**。实际前端包含 AutoDL/第三方登录跳转和 ticket 兑换，推荐通过浏览器完成。验证码、MFA、动态签名、跨域 SSO、HTML 登录页和刷新令牌协议不在通用 JSON 登录器的自动化范围内。

## 查找或替换真实前端接口

1. 在正确租户的资源页面打开 F12 → Network，选择 Fetch/XHR；勾选 Preserve log，清空记录。
2. 刷新“所有主机”、切换页码；若查看逐卡数据，打开“查看占用”。
3. 在响应中搜索页面上已知 GPU 型号或主机 ID，确认此请求返回资源列表，而非静态脚本或用户信息。
4. 检查 Request URL、Method、Payload、Query、Headers 与 Response。右键 Copy as cURL 可在本机查看完整请求；含认证信息的内容不要公开。[Chrome Network 文档](https://developer.chrome.com/docs/devtools/network/reference)
5. 请求 URL → `api.url`；方法 → `api.request.method`；JSON → `api.request.json`；查询参数 → `params`；表单 → `form`。三者按真实请求选择，不把 JSON 内容直接塞到字符串里。
6. 凭据放环境变量或 `.secrets`；保留必要的租户、项目、资源池等参数，去掉浏览器自动生成的 `Content-Length/Host/sec-*` 等头。不要自行发明租户参数。
7. 对照响应填写 `items_path`、`success`、字段映射和分页规则。先 `--sample` 验证脱敏结构，再 `--dry-run` 比较实际页面。

本地址当前前端线索：

| 目的 | 请求 / 字段 |
| --- | --- |
| 主机列表 | `POST https://private.autodl.com/api/v2/machine/list` |
| 分页参数 | `page_index`（从 1 开始）、`page_size`，放 JSON 请求体 |
| 成功及列表 | `code == "Success"`；`data.list` |
| 总记录数 | `data.result_total` |
| 标识和型号 | `machine_id`、`gpu_name` |
| 非多租空闲/总量 | `gpu.idle`、`gpu.total` |
| 多租容量 | `gpu_max_instance_num > 1` 表示该主机开启多租 |
| 逐卡占用 | `POST /api/v2/gpu_stock/list`，JSON 为 `{"machine_id":"实际ID"}` |

以上是前端源代码引用关系，不是服务端文档或对账号权限的确认。不要使用同一打包文件中的 `/admin/v2/...` 管理员接口代替 `/api/v2/...`。

## 通用接口和字段映射

从 `config.generic.example.json` 复制新配置并替换 `.invalid` 占位地址。`availability.adapter: "none"` 关闭 AutoDL 专用共享适配。

路径用点分隔，支持数组下标，例如 `data.items`、`gpu.free`、`data.0.id`；空路径或 `$` 表示当前对象。不是完整 JSONPath：不支持通配符、键名含点、列表展开或任意表达式。复杂结构应在 `sources.py` 或单独适配器中转换。

`mapping.mode: "counts"` 用已有空闲数量；总卡数字段可以省略，空闲数必须存在。`include_values` 可先按原始字段排除 CPU 等记录。默认私有云配置只保留 `machine_type == "gpu"`。

如果接口每条记录是一张卡，可使用：

```json
"mapping": {
  "mode": "cards",
  "fields": {"id": "uuid", "model": "model", "status": "state"},
  "idle_values": ["idle", "free"],
  "idle_require": {"bindings": [[]]}
}
```

这里单条可用数量为 0 或 1；按型号总阈值汇总。所有状态值需来自实际接口。主机内异构卡、MIG 实例、vGPU 配额等不能直接当物理卡相加，需单独定义分组和计数单位。

分页 `mode=page` 的配置见私有云示例。GET 查询使用 `location: "params"`；嵌套页码参数可写 `pagination.page`。游标接口示例：

```json
"pagination": {
  "mode": "cursor",
  "location": "json",
  "parameter": "cursor",
  "initial_cursor": null,
  "next_cursor_path": "data.next_cursor",
  "max_pages": 100
}
```

游标 `null` 或空字符串表示结束。`mode=none` 仅适用于已确认返回完整列表的接口。数量不符、重复页、重复 ID、分页上限、任一页面失败时，整轮不更新。页码分页无法提供数据库事务级一致性：总数不变但翻页期间资源移动的情况仍可能产生暂态变化；有快照版本或游标时优先按后端协议适配。

## 浏览器备选方案

### 接口不能在浏览器外复用

先保存浏览器会话，改 `source: "browser_network"`。它打开配置中的 `page_url`，捕获该页自己发出的指定响应，沿用页面登录逻辑；不把 Cookie/Token 硬编码进脚本。[Playwright 网络文档](https://playwright.dev/python/docs/network)

匹配项是完整 origin + 精确 path + method。若同一路径被不同请求体用于多种查询，应进一步修改 `network()` 的匹配函数。不会自动点击筛选或分页。`total_path` 必须证明响应包含完整范围；若 10 条一页而共有 20 条，会报错。不要把 `single_page_confirmed` 改为 true 来掩盖已知分页。

此模式可处理未开启多租的主机列表。自动识别到多租需要逐卡请求时会要求切换 API 模式，不会悄悄忽略共享口径。

### 没有可复用的 JSON 接口：读取页面

`config.dom.example.json` 提供与“所有主机”表格列顺序对应的起点，读取主机 ID、型号、“空闲算力”的分子/分母及“一卡多租”列。

先用主配置运行登录采集工具，再复制 DOM 示例为另一个本地配置，运行 `--dry-run`。该示例仅适用于 **已确认只有一页且主机均未开启多租** 的情况。它明确要求 `sharing=disabled`，并逐行验证“未开启”。DOM 不能直接判定共享卡绑定。

选择器依赖具体前端版本，应在 Elements 中核对。`ready_selector` 应标记数据已加载的容器；`loading_selector` 用于等待加载遮罩消失；空结果需有明确 `empty_selector`。表头、固定列复制表格、虚拟滚动、iframe、多页和折叠内容需要专门适配，不能把可见行当作全量资源。

通用 DOM 还支持 `hover_selector`、字段 `scope: "page"` 和正则分组；用于需要悬停才能显示空闲数的页面时，应使用能与当前行唯一关联的 tooltip 选择器，避免读到上一行的提示。网站只提供 WebSocket/流式数据时，需要专用订阅解析器；本项目没有宣称自动支持任意协议。

## 运行维护、测试与开源

- 每轮完整查询结束后等待 `interval_seconds`，因此实际周期还包含请求耗时；默认 60 秒、最多 10% 正向随机延迟。共享模式每台主机额外查一次逐卡列表，请按资源规模降低频率。
- 失败按指数退避，上限 `max_backoff_seconds`，再叠加随机延迟；服务端 Retry-After 优先。等待可用 Ctrl+C 中断。
- 状态原子保存到 `state_file`。每个配置使用独立状态文件；进程锁会阻止多个实例同时写同一文件，退出后自动释放，旁边的 `.lock` 文件无需手工删除。重启可继续比较；修改范围、映射、共享口径等会建立新基线，若仍有待发提醒则要求使用新状态文件。
- 长期运行建议使用操作系统自己的进程管理器。不要同时用内置循环和高频计划任务启动多个实例；计划任务调用 `--once` 时也要禁止重叠运行。
- 故障/通知记录可能含机器 ID。安全事项见 [SECURITY.md](SECURITY.md)。

```bash
python -m unittest discover -s tests -v
# Linux/macOS，含本地 Chromium 集成测试
TEST_BROWSER=1 python -m unittest discover -s tests -v
```

```powershell
# Windows，含本地 Chromium 集成测试
$env:TEST_BROWSER='1'
$env:PYTHONUTF8='1'
.venv\Scripts\python.exe -m unittest discover -s tests -v
```

测试只连接本机模拟服务或使用模拟响应，覆盖共享计数、空闲变化、登录失效、分页、通知重试、凭据隔离与浏览器读取，不需要真实 Token。GitHub Actions 的 Linux/Windows 多 Python 版本和浏览器测试已经通过，见 [验证记录](docs/TESTING.md)。

发布时保留 LICENSE 和来源说明，确认提交中没有真实凭据或租户数据。
