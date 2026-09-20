# 实现依据与验证边界

检查日期：2026-09-20。没有运行参考项目，也没有调用创建实例、开机、关机或管理员操作。

## 两个 GitHub 项目

| 项目 | 本次读取的提交 | 实现方式与可借鉴部分 |
| --- | --- | --- |
| [Jiayi-Fu/autodl-gpu-monitor](https://github.com/Jiayi-Fu/autodl-gpu-monitor) | `2c93b563f3202cce6507944bb15ec317d6d403d8` | Python Requests 直接查询，Authorization 认证，JSON 配置，Server酱提醒。 |
| [wangzhao-desgin/autodl-gpu-monitor](https://github.com/wangzhao-desgin/autodl-gpu-monitor) | `3579d10f974a34cf5db333484e22a78b62d28933` | Chrome 扩展依托已登录的实例列表，读取 DOM、悬停提示，后台定时检查并通知。 |

第一个项目的 [watch.py](https://github.com/Jiayi-Fu/autodl-gpu-monitor/blob/2c93b563f3202cce6507944bb15ec317d6d403d8/watch.py) 硬编码型号与地区，通过公有云 `/api/v1/machine/region/gpu_type` 查询。另一个 [gpu.py](https://github.com/Jiayi-Fu/autodl-gpu-monitor/blob/2c93b563f3202cce6507944bb15ec317d6d403d8/gpu.py) 查询 `/api/v1/user/machine/list`，依据 `gpu_idle_num` 筛选，包含购买实例的代码。本项目重新实现查询与提醒，不包含购买流程。

[login_helper.py](https://github.com/Jiayi-Fu/autodl-gpu-monitor/blob/2c93b563f3202cce6507944bb15ec317d6d403d8/login_helper.py) 提供手机号密码或微信扫码换 ticket/token；这些地址是公有云流程，不能直接套用私有云 SSO。主循环在无资源时等待 30 秒。[main.py](https://github.com/Jiayi-Fu/autodl-gpu-monitor/blob/2c93b563f3202cce6507944bb15ec317d6d403d8/main.py) 的监控分支把 `watch_gpu` 返回的字典 `extend` 到数组中，实际上会迭代字典键；字典非空不等于存在满足条件的空闲卡。新实现强制读取数量字段，不沿用该判定。

第二个项目的 [content.js](https://github.com/wangzhao-desgin/autodl-gpu-monitor/blob/3579d10f974a34cf5db333484e22a78b62d28933/content.js) 从 Element 表格提取名称和状态，触发悬停并解析“GPU 空闲/总量”，同时包含开关机按钮操作。[background.js](https://github.com/wangzhao-desgin/autodl-gpu-monitor/blob/3579d10f974a34cf5db333484e22a78b62d28933/background.js) 使用定时器、防并发检查及通知，目标标签页写死为公有云实例列表。我们借鉴复用登录会话的思路，采用人工登录捕获认证头/保存浏览器状态，以及可配置的读取适配。

两个项目的监控对象不同：前者主要查询公有云可租资源，后者关注已有实例能否重新带卡运行。它们均不能证明私有云“所有主机”页面使用同一个接口或同一套 DOM。新项目的 Python 实现独立编写，发布包不包含参考项目代码或网站前端源码。

## 目标私有云页面

目标：[https://private.autodl.com/console/machine](https://private.autodl.com/console/machine)。公开 HTML 指向一组前端资源；未登录即可取得这些静态代码，但不能据此获知用户资源或权限。

| 前端资源 | 静态分析得到的关联 |
| --- | --- |
| [index.836fd3b2.js](https://private.autodl.com/assets/index.836fd3b2.js) | 路由 machine 指向主机页；请求拦截器将 localStorage `token` 原样放入 Authorization；处理 `Success`、`AuthorizeFailed` 等业务码。表格组件从 list/result_total 读取分页数据。 |
| [index.c3daf3f8.js](https://private.autodl.com/assets/index.c3daf3f8.js) | 主机页传入 page_index/page_size；GPU 主机的 gpu_max_instance_num 大于 1 时显示开启多租，否则显示“未开启”。 |
| [all-machine.c6b7e82f.js](https://private.autodl.com/assets/all-machine.c6b7e82f.js) | 普通用户主机列表为 POST api/v2/machine/list；逐卡接口为 POST api/v2/gpu_stock/list。 |
| [options.9752bbfd.js](https://private.autodl.com/assets/options.9752bbfd.js) | 型号字段 gpu_name，空闲/总量 gpu.idle/gpu.total；逐卡列有 gpu_uuid、reserved、gpu_bindings 与旧版 instance_uuid。reserved 的显示语义是“是否被占用满”。 |
| [gpu-occupy.59b06bd5.js](https://private.autodl.com/assets/gpu-occupy.59b06bd5.js) | 打开占用抽屉，提交 machine_id，读取 data.list；页面关闭逐卡表格分页。 |

资源文件名带构建哈希，网站升级后链接可能失效。未来维护时从目标 HTML 的实际 script 和路由重新定位，不应盲目保留这些文件名。

界面中的路由、列顺序和字段显示可用于核对是否采用了这套前端。网站打包代码包含功能不等于目标租户启用了功能。默认自动模式会按每台主机的实际字段判断；显式开关和两种空闲定义用于兼容不同部署。

## 已验证与待验证

已验证：来源代码关联、配置生成、离线响应解析、本地 HTTP 模拟器中的分页/登录/提醒，以及本地 Chromium 响应捕获和 DOM 读取。测试无真实凭据，不向 AutoDL 发送资源操作。

待真实环境验证：Token 的有效期和租户绑定、服务端响应是否与当前前端一致、逐卡权限、字段语义/空值、多租的具体预约策略、DOM 选择器及浏览器登录恢复。程序遇到缺失字段或不完整响应会报错，而不会报告为零卡。

“整卡完全空闲”的多租判定是依据绑定字段构造的保守适配，并非后端公开契约；空绑定数组中若包含占位元素，将保守视为非空闲。未建模的 CPU/内存配额和调度策略可能继续限制最终创建实例。

## 文档参考

- [Requests Session、TLS 与代理](https://requests.readthedocs.io/en/latest/user/advanced/)
- [Playwright 认证状态](https://playwright.dev/python/docs/auth)
- [Playwright 网络响应捕获](https://playwright.dev/python/docs/network)
- [Chrome DevTools Network](https://developer.chrome.com/docs/devtools/network/reference)
- [GitHub checkout](https://github.com/actions/checkout)、[setup-python](https://github.com/actions/setup-python)：CI 文件使用本次文档列出的 v7。
