# 配置参考

配置文件使用 JSON，路径相对配置文件所在目录。认证项支持 `${ENV_NAME}` 环境变量占位符；修改配置后重启进程。

## 找到实际接口

在目标租户「所有主机」页面打开开发者工具 Network，筛选 Fetch/XHR，刷新页面或翻页。在响应中查找页面显示的型号/主机 ID，确认返回的是资源列表；打开「查看占用」定位逐卡接口。核对 URL、Method、Payload、Headers 与 Response。[Chrome Network 文档](https://developer.chrome.com/docs/devtools/network/reference)

| 实际请求 | 配置项 |
| --- | --- |
| 地址、方法 | `api.url`、`api.request.method` |
| JSON / 查询参数 / 表单 | `api.request.json` / `params` / `form` |
| 列表路径 | `api.items_path` |
| 成功与鉴权失败码 | `api.success.path/values/auth_values` |
| 身份、租户及 CSRF 头 | `auth.headers` 或本地凭据文件 |
| 字段路径 | `mapping.fields` |
| 分页参数与总数 | `api.pagination` |

Copy as cURL 可在本机帮助核对请求，但包含认证信息，不应粘贴到公开 Issue。保留真实租户/项目参数，不照搬 `Host`、`Content-Length`、`sec-*` 等浏览器头。

默认 AutoDL 私有云适配：

| 项目 | 地址或字段 |
| --- | --- |
| 主机列表 | `POST https://private.autodl.com/api/v2/machine/list` |
| 分页 | JSON `page_index` 从 1 开始，`page_size` 指定每页条数 |
| 成功 / 列表 / 总数 | `code == "Success"` / `data.list` / `data.result_total` |
| 标识 / 型号 | `machine_id` / `gpu_name` |
| 非多租空闲 / 总卡数 | `gpu.idle` / `gpu.total` |
| 多租容量 | `gpu_max_instance_num`，大于 1 表示多租 |
| 逐卡列表 | `POST /api/v2/gpu_stock/list`，JSON `{"machine_id":"实际ID"}` |
| 逐卡字段 | `gpu_uuid`、`reserved`、`gpu_bindings`、旧版 `instance_uuid` |

内部字段需与实际部署核对。`reserved` 按页面的「是否被占用满」解释；共享卡按物理卡计数，不换算为可租实例槽位。逐卡接口默认按完整列表处理；若部署版本有分页，需添加相应适配，不能忽略后续页。

## 认证

### 浏览器会话采集

```bash
python browser_login.py --config config.json
```

人工完成扫码、验证码或 SSO，进入目标列表并触发成功请求，再回终端按回车保存。只捕获与 `api.url` 同源、同路径、同方法的资源响应及允许的认证头。

- `.secrets/credentials.json`：绑定 API origin 的认证头，供 API 模式读取。
- `.secrets/browser-state.json`：Cookie、localStorage、IndexedDB，供浏览器模式读取。
- `.secrets/captured-request.json`：目标请求的方法、地址和请求体。
- `--save-sample` 额外保存响应，默认不落盘。

`browser.channel` 可选 `msedge` 或 `chrome`；省略时使用 Playwright Chromium。浏览器状态不包含 sessionStorage，且可能受设备/IP 绑定限制。[Playwright 认证文档](https://playwright.dev/python/docs/auth)

### Token / Cookie

直接配置时，将 `auth` 替换为：

```json
"auth": {
  "headers": {"Authorization": "${PRIVATE_GPU_TOKEN}"},
  "login": {"enabled": false}
}
```

AutoDL 私有云前端通常将 `token` 原样放入 `Authorization`；是否添加 `Bearer` 以实际请求为准。Cookie 使用 `"Cookie": "${PRIVATE_GPU_COOKIE}"`，其他必要请求头同样放入 `auth.headers`。

`credentials_file` 与 `headers` 同时存在时，后者覆盖同名认证头。凭据文件每次请求重新读取；环境变量由进程启动时继承。会话过期后重新采集，脚本不会绕过 MFA 或权限检查。

可配置 `auth.csrf: {"cookie_name":"XSRF-TOKEN","header_name":"X-XSRF-TOKEN","url_decode":true}`，从会话 Cookie 或显式 Cookie 头复制 CSRF 值。

### JSON 登录流程

`examples/auth.login.json` 是通用多步登录结构，需替换实际地址、请求参数和响应路径，不是 AutoDL 密码登录接口。每步支持 `request`、`success`、`save`；例如 `save: {"LOGIN_TOKEN":"data.token"}` 后，认证头可引用 `${LOGIN_TOKEN}`。Set-Cookie 自动保存在 Session 中。

启用 `auth.login.enabled` 后启动时登录，鉴权失败每轮最多再登录一次。验证码、动态签名、跨域 SSO 和刷新令牌协议需要按站点单独适配，优先使用人工浏览器登录。

## 字段与筛选

自定义接口从 `config.generic.example.json` 开始，替换 `.invalid` 地址，并保持 `availability.adapter: "none"`。

字段路径以点分隔，支持数组下标；空路径或 `$` 表示当前对象。不是完整 JSONPath，不支持通配符、列表展开或键名含点。

- `mapping.mode: "counts"`：每条记录自带空闲卡数；总数字段可省略，空闲字段不能缺失。
- `mapping.mode: "cards"`：每条记录代表一张卡，依据 `idle_values` 与可选 `idle_require` 判断空闲，单条数量为 0 或 1。
- `mapping.include_values`：预先排除不需要的原始记录，默认私有云仅保留 `machine_type == "gpu"`。
- `filters.regions/allowed_statuses`：需先映射 `region/status`，按后端实际值筛选。
- `min_free_per_resource`：单主机阈值；`min_total_free_per_model`：通过单主机筛选后的同型号合计。不同型号不相加。
- `only_free: false` 允许零空闲候选，还需将单资源阈值设为 0；是否满足合计阈值另行判断。

GPU 利用率、MIG 实例、vGPU 配额不等于物理卡数，需要单独定义单位和适配。

## 分页与完整性

页码分页示例见私有云配置；GET 查询使用 `location: "params"`，JSON 请求使用 `location: "json"`。游标分页：

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

游标 `null` 或空字符串表示结束。`mode: "none"` 仅适用于已确认返回完整列表的接口。记录数量不符、重复 ID、重复页、超过分页上限或任一请求失败时，整轮快照不更新。普通页码分页不具备事务一致性，后端若支持快照版本应优先使用。

## 浏览器数据源

`source: "browser_network"` 在已登录页面中捕获自然发出的响应，适用于无法在浏览器外复用的请求。按完整 origin、路径与方法匹配；不会自动操作分页或筛选。`browser.total_path` 必须证明捕获了完整范围。[Playwright 网络文档](https://playwright.dev/python/docs/network)

`source: "browser_dom"` 使用配置选择器读取表格。`config.dom.example.json` 仅适用于已确认完整单页、所有主机均未开启多租的情况；要求 `sharing: "disabled"` 并逐行核验「未开启」。选择器、加载结束和空表标记需与页面一致。

两种浏览器模式均不能代替多租逐卡查询；需要该能力时使用 API 模式。虚拟滚动、iframe、WebSocket 等需专门适配，不能把可见行当作全部资源。
