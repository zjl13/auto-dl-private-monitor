# 完整使用教程：从安装到微信收到 GPU 通知

适用版本：0.2.0。默认页面：<https://private.autodl.com/console/machine>。

本教程以 Windows PowerShell 为主。你不需要手工复制私有云 Cookie：工具会打开独立浏览器，让你自行登录，再保存资源查询所需的会话。微信通知使用 Server酱 Turbo，SendKey 也只在本机输入。

## 1. 先明确运行后的效果

脚本定期读取你的账号可见的 GPU 资源，筛选型号和空闲数量。有状态变化时，会在终端显示并通过已配置的通道提醒。默认每轮查询完成后等待约 60–66 秒。

例如某台 RTX 4090 主机由 0 张空闲变成 2 张空闲，且符合你的筛选条件，就会生成资源变化事件。首次成功查询后还可以收到一条“GPU 监控已启动”微信消息。

程序只查询资源和发送通知，不创建实例、不自动开关机、不抢卡。电脑或运行脚本的服务器必须保持开机、联网；微信手机不需要与它在同一局域网。

接口和多租字段来自私有云前端代码分析，尚未使用真实账号完成适配验证。首次务必做下文的卡数核对；自动化测试通过不等于所有私有云部署均已验证。

## 2. 准备账号与软件

| 项目 | 要求 |
| --- | --- |
| Python | 3.10+；本次本地测试版本为 3.12.10。建议使用 3.12 或 3.13 系列。 |
| AutoDL 私有云账号 | 能正常登录目标租户并看到“所有主机”。 |
| 微信通知 | Server酱 Turbo 账号、已配置微信通道及 SCT 开头的 SendKey。 |
| 网络 | 能访问目标私有云和 Server酱；内部部署可能还需要 VPN 或内部 CA。 |

先打开 PowerShell，输入：

```powershell
python --version
```

应输出 `Python 3.x.x`。如果找不到命令，或打开了应用商店，先从 [Python 官方 Windows 页面](https://www.python.org/downloads/windows/) 安装标准 Python 发行版，再重新打开终端。不要下载 embeddable 嵌入式包来按本教程运行。

## 3. 下载项目并进入正确文件夹

仓库：[zjl13/auto-dl-private-monitor](https://github.com/zjl13/auto-dl-private-monitor)。

在仓库页面点击 **Code → Download ZIP**，解压。进入能看到这些文件的那一层：

```text
monitor.py
browser_login.py
setup_wechat.py
requirements.txt
requirements-browser.txt
config.private.example.json
```

在此文件夹空白处右键选择“在终端中打开”，或在资源管理器地址栏输入 `powershell` 回车。运行以下命令核对当前位置：

```powershell
Get-ChildItem monitor.py
```

如果提示找不到文件，说明目录不正确；有些 ZIP 解压后会多一层同名文件夹。

熟悉 Git 的用户也可以：

```powershell
git clone https://github.com/zjl13/auto-dl-private-monitor.git
Set-Location auto-dl-private-monitor
```

## 4. 第一次安装依赖

按顺序执行；任何一步报错都应先解决，再继续下一步：

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-browser.txt
.venv\Scripts\python.exe -m playwright install chromium
```

第三条命令会下载工具需要的 Chromium，首次可能需要等待。这里直接调用虚拟环境里的 Python，不需要运行激活脚本，也无需修改 PowerShell 执行策略。

接着创建个人配置；以下写法不会覆盖已经存在的 `config.json`：

```powershell
if (-not (Test-Path -LiteralPath 'config.json')) {
    Copy-Item config.private.example.json config.json
}
```

`config.private.example.json` 是公开模板；以后修改自己的 `config.json`。

安装成功可以这样验证：

```powershell
.venv\Scripts\python.exe monitor.py --version
.venv\Scripts\python.exe monitor.py --config config.private.example.json --sample examples/sample.private.json
```

第二条是离线演示，不需要登录，不查询真实资源，也不发送通知。示例应显示一个空闲 2 张卡的演示 RTX 4090 主机、一个空闲 0 张卡的 A100 主机，并排除演示 CPU 主机。这些是构造的数据，不是你账号中的资源。

## 5. 保存私有云登录会话

执行：

```powershell
.venv\Scripts\python.exe browser_login.py --config config.json
```

接下来按这个顺序操作：

1. 工具打开一个独立浏览器窗口；它不会直接使用你平时浏览器的登录状态。
2. 在该窗口中完成 AutoDL 登录，包括扫码、验证码或第三方登录。
3. 选择要监控的私有云租户，打开“所有主机”。同一账号有多个租户时，务必选对。
4. 在该窗口刷新一次“所有主机”页面，或切换一次页码，让页面请求资源数据。
5. 回到终端，等看到“已捕获一条成功的资源列表响应及其认证头”。
6. **在终端按回车**保存。不要只关闭浏览器而不保存。

成功后会生成：

| 文件 | 用途 |
| --- | --- |
| `.secrets/credentials.json` | 普通 API 轮询使用的认证头。 |
| `.secrets/browser-state.json` | 浏览器备用模式恢复登录状态。 |
| `.secrets/captured-request.json` | 捕获的资源请求方法、地址和请求体，便于本地排查。 |

不需要把这些文件内容复制出来，也不要发到聊天或 GitHub。原始响应只有增加 `--save-sample` 时才会额外保存到 `.secrets/sample-response.json`。

## 6. 核对真实型号与卡数

执行：

```powershell
.venv\Scripts\python.exe monitor.py --config config.json --dry-run
```

这一步只查询一次，输出标准化结果，不发通知，也不建立或修改监控基线。

核对 JSON 中的字段：

| 输出 | 含义 |
| --- | --- |
| `resources` | 型号/区域筛选范围内的资源，包含当前 0 空闲的主机。 |
| `model` | GPU 型号，应与页面匹配。 |
| `free` / `total` | 当前选定口径的空闲/总卡数。未开启多租时对应页面的“空闲算力”。 |
| `eligible` | 达到单机数量、状态等条件的资源。 |
| `free_by_model` | 合格资源按同型号汇总的卡数。 |
| `available` | 是否存在满足合计数量要求的型号。 |

例如页面当时显示 `2/7`，非多租模式下应得到 `free: 2, total: 7`。若不一致，先检查时间差、租户、分页与多租口径，不要直接长期开着。

`available: false` 也可能是正常结果：查询成功，但没有满足筛选条件的卡。报“会话失效”“字段缺失”等错误才需要排查。

## 7. 设置需要的 GPU 和卡数

先停止正在运行的监控，编辑配置：

```powershell
notepad config.json
```

找到完整的 `filters` 对象，按需要替换。以下示例关注 A40 或 RTX 4090，每台至少 1 张空闲卡：

```json
"filters": {
  "models": ["A40", "RTX 4090"],
  "model_match": "contains",
  "regions": [],
  "only_free": true,
  "min_free_per_resource": 1,
  "min_total_free_per_model": 1,
  "allowed_statuses": []
}
```

这是配置中的一个片段，不能把整个配置文件替换成它。保留相邻对象之间的逗号，使用英文双引号，不写注释或末尾多余逗号。

常用修改：

| 目的 | 设置 |
| --- | --- |
| 只监控 RTX 4090 | `models: ["RTX 4090"]`。 |
| 所有 GPU 型号 | `models: []`。 |
| 同一台机器至少 2 卡 | `min_free_per_resource: 2`，合计阈值也可设为 2。 |
| 同型号跨主机合计 4 卡 | 单机阈值设 1，`min_total_free_per_model: 4`。不表示这 4 卡在同一台机器。 |
| 区分 4090 和 4090D | `model_match: "exact"`，填写 `--dry-run` 得到的完整型号名。 |

默认用包含匹配且不区分大小写。关注零空闲资源也不必把 `only_free` 关闭，程序会保留它们以检测后续从 0 到有卡的变化。

修改后再执行一次 `--dry-run`，确认 JSON 格式正确且筛选符合预期。

## 8. 一卡多租应该怎么设置

在现有 `availability` 对象里，只改以下两个字段，保留该对象的其他字段：

```json
"sharing": "auto",
"free_definition": "exclusive"
```

| 模式 | 适用情况 |
| --- | --- |
| `auto` | 建议作为起点。每台主机读取多租容量字段，适合混合部署。 |
| `disabled` | 你明确只监控未开启多租的机器。若接口实际报告启用了多租，程序会报不一致。 |
| `enabled` | 强制使用逐卡占用接口确认，需要“查看占用”的相应权限。 |

| 空闲定义 | 含义 |
| --- | --- |
| `exclusive` | 多租时要求整张卡没有实例绑定，且未被预留满。 |
| `allocatable` | 多租时统计仍未占满、可以继续共享分配的卡。 |

例如 3 张卡分别为全空、部分占用、占满：`exclusive` 算 1 张，`allocatable` 算 2 张。两者计数单位都是卡，不是可创建实例的槽位。

当前页面均显示“未开启”时，可保留默认 `auto + exclusive`。启用多租后需要逐卡查询；权限不足或绑定字段缺失时程序会报错，不会凭空猜卡数。GPU 利用率、显存使用率、配额和最终能否启动实例不由此计数保证。

## 9. 绑定微信并发送测试消息

先到 [Server酱 Turbo](https://sct.ftqq.com) 微信扫码登录，按控制台指引配置微信消息通道，复制 **SCT 开头**的 SendKey。不要选用于独立 App 的 `sctp` Key；普通微信服务号通道与企业微信群机器人也不是同一种接收端。[官方获取说明](https://sct.ftqq.com/docs/getting-started/sendkey/)

回到项目目录：

```powershell
.venv\Scripts\python.exe setup_wechat.py --config config.json
```

粘贴 SendKey 并回车。**输入时没有字符显示是正常的。** 工具会将密钥保存到 `.secrets/serverchan.json`，启用微信通知和启动提醒，保留原有型号与接口设置。

然后测试：

```powershell
.venv\Scripts\python.exe monitor.py --config config.json --notify-test
```

你应在终端看到服务已接受，在手机微信中收到“GPU 监控通知测试”。这一步不依赖云端登录、不查询 GPU、不修改监控状态。

如果终端成功但手机没消息，到 Server酱控制台检查消息日志、通道绑定、微信关注/屏蔽状态和额度，不要把测试命令放进循环。官方额度会调整，以控制台为准。[官方通道与额度说明](https://sct.ftqq.com/docs/getting-started/channels/)

## 10. 正式启动并验证

```powershell
.venv\Scripts\python.exe monitor.py --config config.json
```

预期行为：

1. 终端打印读取了多少条资源、筛选范围和是否满足条件。
2. 第一次完整资源查询成功后发送“GPU 监控已启动”通知，当前没有空闲卡也会发送。
3. 程序继续轮询；资源不变时不会每轮发微信。
4. 卡数、状态、新增/移出范围等变化会提醒；故障和恢复也会提醒。

如果一开始云端登录失败，就先提醒故障，而不会声称启动成功。失败会延长下一次查询等待时间。

看到启动消息后，可正常使用已有资源，等待一次自然的资源变化，核对收到的通知。无需为了测试而专门创建或关闭付费实例。

## 11. 停止、重启和日常维护

在监控终端按 **Ctrl+C** 停止。正常停止不会额外发送一条微信。

第二天或重启电脑后：打开项目目录中的终端，重新运行上面的启动命令即可。依赖不需要重复安装；配置与有效会话会保留。

- 终端关闭、电脑关机或休眠后，程序不能继续按时监控。
- 默认约每分钟查询一次。把 `poll.interval_seconds` 改为 120 可减小请求频率；共享主机每台还需额外查询占用信息。
- 不要对同一配置重复启动多个进程。相同状态文件有进程锁，第二个实例会退出。
- 修改配置后重启。更换租户或大幅调整监控范围时，建议将 `state_file` 改成另一个名称，以免混淆历史事件。
- `.state/` 用来记住上次资源状态及待发通知。重启后可继续比较，通常不应随便删除。
- Server酱默认成功发送间隔至少 60 秒、失败后至少 900 秒重试。因此多条消息可能依次延迟送达。服务接受不等于手机已收到。
- 计划任务可用 `--once` 执行一轮，但它不创建启动通知。不要让计划任务与长期循环同时运行。

## 12. 登录过期或切换租户

遇到 401/403、`AuthorizeFailed`、会话失效或权限提示时：

1. Ctrl+C 停止监控。
2. 再运行 `browser_login.py --config config.json`。
3. 在弹出的浏览器重新登录，选对租户，刷新主机列表，等捕获成功后回终端按回车。
4. 运行 `--dry-run` 核对，再重新启动监控。

这些操作不需要重新配置微信。API 模式也会重新读取更新后的会话文件，但首次排错建议按上述停止、验证、启动顺序进行。

如果设置过 `PRIVATE_GPU_TOKEN` 或 `SERVERCHAN_SENDKEY` 等环境变量，注意环境变量与文件配置的优先级。微信的 `SERVERCHAN_SENDKEY` 会优先于密钥文件，旧环境变量可能使新密钥没有生效。

## 13. Linux/macOS 和无桌面服务器

有桌面的 Linux/macOS，进入项目目录后：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-browser.txt
python -m playwright install chromium
test -f config.json || cp config.private.example.json config.json
python browser_login.py --config config.json
python monitor.py --config config.json --dry-run
python setup_wechat.py --config config.json
python monitor.py --config config.json --notify-test
python monitor.py --config config.json
```

无桌面的服务器建议只跑 API 模式：先在可信的桌面电脑采集登录状态，把自己的 `config.json`、`.secrets/credentials.json` 通过安全方式传到服务器项目目录。服务器安装 `requirements.txt`，在服务器上配置微信，再测试和运行。无需复制整个 `.venv` 或普通浏览器的用户目录。

凭据可能绑定设备/IP；若服务器无法复用，不要绕过限制，改用组织授权的登录方案。需要内部 VPN、代理或 CA 时，按实际网络配置处理。

Linux 长期运行建议采用系统服务；应以普通专用账号运行、指定项目工作目录和 `.venv/bin/python`、只启动一个监控进程。服务不具备桌面登录能力，因此先完成会话配置。不要把真实凭据写到公开的服务文件示例中。

## 14. 常见故障速查

| 现象 | 处理 |
| --- | --- |
| 找不到 monitor.py | 进入包含此文件的项目根目录。 |
| 找不到 python / pip | 核对 Python 安装；后续都用 `.venv\Scripts\python.exe -m pip`。 |
| No module named requests | 用同一个虚拟环境重新安装 requirements.txt。 |
| 浏览器可执行文件不存在 | 执行 `.venv\Scripts\python.exe -m playwright install chromium`。 |
| 登录后没有捕获成功提示 | 确认在工具打开的窗口、正确租户和主机页，刷新或切换分页；检查 api.url。 |
| 接口返回重定向/非 JSON | 可能是登录失效或接口地址不对；先重新登录，仍失败则按 README 定位实际前端接口。 |
| 字段缺失/重复 ID/分页不完整 | 不把错误改成 0；对照脱敏响应调整映射及分页，见 README。 |
| 多租模式无权限查看占用 | 需管理员授予合法只读权限，或改用被授权的接口。 |
| 配置格式错误 | 使用英文双引号、正确逗号；不要只保存一个 JSON 片段。 |
| 密钥输入没有显示 | getpass 的正常保密行为，粘贴后回车即可。 |
| 微信配置后不发送 | 先单独 `--notify-test`；检查旧环境变量、通道绑定与额度。 |
| 没有启动成功通知 | 检查 notify_startup 是否开启；需要一次成功查询；--once 不发送启动事件。 |
| 同一状态文件已有进程 | 先停止前一个进程；不要删除锁文件来强行并行。 |
| 配置变化且还有待发提醒 | 使用新的 state_file；旧提醒是否继续投递由你决定。 |

## 15. 分享代码和升级时保留什么

可以公开：Python 源码、README、docs、tests、依赖清单、`config.*.example.json` 等脱敏示例。

不要公开：`config.json`、`.secrets/`、`.state/`、HAR、真实响应、带账号/租户/主机信息的截图。`.gitignore` 已配置常见文件，但忽略规则不能从旧提交中撤回曾经泄漏的内容。

升级前停止监控并在本机备份个人配置。替换源码和公开示例，保留自己的配置/凭据；不要用新示例覆盖个人配置。虚拟环境依赖可按新版本清单更新，再做 `--dry-run` 和通知测试。

更多配置参考：[README](../README.md)、[微信专题](WECHAT.md)、[接口研究](RESEARCH.md)、[安全说明](../SECURITY.md)、[测试记录](TESTING.md)。
