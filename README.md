# Realtime OI Dashboard

一个用于查看 **Binance USDT 永续合约** 行情、持仓量（OI）变化和市场信号的网页面板。

## 安装

需要 Python 3.10 或更高版本。

在项目目录中运行：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

## 启动

```bash
.venv/bin/python main.py
```
```
http://127.0.0.1:8777
```
### 用手机访问本地面板

手机和电脑连接同一个网络，然后这样启动：

```bash
.venv/bin/python main.py --host 0.0.0.0 --port 8777
```
```
http://192.168.xxx.xxx:8777
```

其中 `192.168.xxx.xxx` 需要替换成电脑当前的局域网 IP。

## 可选设置

正常使用不需要修改这些参数。需要调整访问方式、更新速度或缓存时间时，可以在启动命令后面添加：

| 参数 | 默认值 | 作用 |
|---|---:|---|
| `--host` | `127.0.0.1` | 面板监听地址。只在当前电脑访问时保持默认；需要让同一网络里的手机访问时使用 `0.0.0.0`。 |
| `--port` | `8777` | 面板使用的端口。端口被其他程序占用时可以更换。 |
| `--oi-batch-size` | `25` | 每批更新的合约数量。调小会降低单批请求量，但完成全部更新需要更久。 |
| `--oi-batch-delay` | `1` 秒 | 两批 OI 请求之间的等待时间。网络不稳定或请求过快时可以调大。 |
| `--oi-workers` | `3` | 同时发送的 OI 请求数量。调小可以降低请求压力。 |
| `--ticker-cache-seconds` | `10` 秒 | OI 与 Signal Scan 共用的 24 小时行情缓存时间。调大可以减少请求次数。 |
| `--funding-cache-seconds` | `3600` 秒 | 资金费率备用数据的缓存时间。 |
| `--market-cap-refresh-seconds` | `3600` 秒 | 市值和 FDV 的刷新间隔，默认每小时更新一次。 |
| `--snapshot-save-interval` | `10` 秒 | 当前 OI 状态保存到本地文件的间隔。 |
| `--signal-scan-interval` | `60` 秒 | 趋势和波动率信号重新扫描的间隔。 |
| `--disable-cvd` | 关闭 | 禁用后端全币种 CVD 服务。 |
| `--cvd-universe-refresh-seconds` | `900` 秒 | 检查 USDT 永续合约新增与下架的间隔。 |
| `--cvd-target-symbols-per-shard` | `150` | 每个动态 CVD WebSocket 分片的软容量。 |
| `--cvd-backfill-requests-per-second` | `4` | CVD 缺失分钟补数的请求速率。 |
| `--cvd-backfill-workers` | `2` | CVD 补数工作线程数量。 |
| `--disable-cvd-persist` | 关闭 | 禁用 CVD 重启恢复快照。 |
| `--cvd-persist-interval-seconds` | `300` 秒 | CVD JSON 快照的原子保存间隔。 |

例如，网络不稳定或请求过快时，可以降低 OI 更新速度：

```bash
.venv/bin/python main.py \
  --oi-batch-size 10 \
  --oi-batch-delay 2 \
  --oi-workers 1
```

查看全部启动选项：

```bash
.venv/bin/python main.py --help
```

## 测试

运行后端测试：

```bash
.venv/bin/python -m unittest discover -s tests -v
```

检查前端文件：

```bash
node realtime_oi_dashboard/scripts/check-static-js.mjs
```

## 代码结构

下面只列出 Git 管理的项目文件；运行时生成的 `data/`、虚拟环境、缓存和
`__pycache__/` 不在树中。每个文件右侧是它的主要职责。

```text
RealtimeOIDashboard/
├── main.py                              # 最小启动入口，调用应用 bootstrap
├── requirements.txt                    # Python 运行依赖
├── README.md                           # 安装、运行、测试和架构说明
├── .gitignore                          # Git 忽略规则
├── .vscode/
│   └── launch.json                     # VS Code 本地调试配置
├── realtime_oi_dashboard/
│   ├── __init__.py                     # Python 顶层包标记
│   ├── bootstrap.py                    # 组合根：创建服务、注入依赖并负责进程启停
│   ├── cli.py                          # 命令行参数、默认值和参数校验
│   ├── server.py                       # HTTP 服务装配与 API 路由绑定
│   ├── web.py                          # HTML、静态资源和 JSON 响应的通用处理器
│   ├── index.html                      # Dashboard 页面结构和模块入口
│   ├── package.json                    # 前端 ES Module 类型与 Node 测试命令
│   │
│   ├── application/                    # 后端用例层：编排流程，不处理外部协议细节
│   │   ├── __init__.py                 # application 包标记
│   │   ├── background_service.py       # 把 poller 包装为可启停、可检查的后台线程服务
│   │   ├── oi/                         # OI 功能的应用流程
│   │   │   ├── __init__.py             # OI application 子包标记
│   │   │   ├── batch.py                # 并发抓取一批币种并隔离单币种失败
│   │   │   ├── batch_selector.py       # 按固定顺序循环选择下一批币种
│   │   │   ├── health.py               # 记录近期错误、服务时钟和健康状态
│   │   │   ├── history.py              # 加载、缓存和刷新历史 OI 基准
│   │   │   ├── market_snapshot.py      # 为一轮 OI 更新收集共享行情、资金费率和市值
│   │   │   ├── poller.py               # OI 主协调器，串联更新流程并发布当前状态
│   │   │   ├── presenter.py            # 把内部 OI 状态转换成稳定的 API payload
│   │   │   ├── runtime.py              # 管理 OI 轮询线程、线程池和停止信号
│   │   │   └── symbol_refresher.py     # 刷新、校验合约列表并识别新增币种
│   │   ├── signal_scan/                # Signal Scan 功能的应用流程
│   │   │   ├── __init__.py             # Signal Scan application 子包标记
│   │   │   ├── executor.py             # 有上限地并发执行逐币种信号计算
│   │   │   ├── kline_cache.py          # 管理已校验 K 线历史和 LRU 淘汰
│   │   │   ├── market_snapshot.py      # 获取并整理扫描需要的币种和 24h 行情
│   │   │   └── poller.py               # 调度扫描、聚合结果并发布 Signal Scan 状态
│   │   └── cvd/                        # CVD 功能的应用流程
│   │       ├── __init__.py             # CVD application 子包标记
│   │       ├── backfill.py              # 以限速队列补齐缺失的分钟成交数据
│   │       ├── poller.py                # 协调币种池、WebSocket 分片、补数和快照
│   │       ├── presenter.py             # 生成对外的 CVD 数据和服务健康状态
│   │       ├── shard_allocator.py       # 根据币种数和负载决定、分配 CVD 分片
│   │       ├── snapshot_service.py      # 调度 CVD 快照恢复与定时持久化
│   │       ├── store.py                 # 线程安全地保存 CVD 窗口并发布不可变快照
│   │       └── universe.py              # 发现当前有效的 USDT 永续合约集合
│   │
│   ├── domain/                         # 后端领域层：纯规则、计算和内存模型，不是前端
│   │   ├── __init__.py                 # domain 包标记
│   │   ├── errors.py                   # 停止轮询等内部控制流异常
│   │   ├── market_cap.py               # Binance 币种与 CoinGecko 市值数据的匹配规则
│   │   ├── market_data.py              # Binance 行情响应解析、合并和刷新校验规则
│   │   ├── parsing.py                  # 严格、安全的数字转换工具
│   │   ├── symbols.py                  # Binance symbol 格式校验规则
│   │   ├── oi/
│   │   │   ├── __init__.py             # OI domain 子包标记
│   │   │   ├── history_points.py       # 解析 OI 历史点并计算历史基准
│   │   │   ├── row.py                  # 用已抓取数据纯计算单行 OI 指标
│   │   │   └── state.py                # OI 更新模型和内存状态容器
│   │   ├── signal_scan/
│   │   │   ├── __init__.py             # Signal Scan domain 子包标记
│   │   │   ├── klines.py               # K 线复制、合并、裁剪和时序校验规则
│   │   │   └── rules.py                # EMA 趋势及波动率信号的计算规则
│   │   └── cvd/
│   │       ├── __init__.py             # CVD domain 子包标记
│   │       └── model.py                # 固定内存分钟桶及 CVD 方向计算模型
│   │
│   ├── infrastructure/                 # 基础设施层：外部 API、WebSocket、HTTP 和存储适配器
│   │   ├── __init__.py                 # infrastructure 包标记
│   │   ├── http.py                     # 带重试、限流和停止支持的线程安全 JSON 客户端
│   │   ├── binance/
│   │   │   ├── __init__.py             # Binance integration 子包标记
│   │   │   ├── cvd_stream.py           # Binance CVD WebSocket 分片连接与自动重连
│   │   │   ├── futures_client.py       # OI、资金费率和历史数据的 Binance 客户端
│   │   │   ├── market_data.py          # 共享 ticker/24hr、exchangeInfo 的直连适配器
│   │   │   ├── rest_cache.py           # 共享 REST 缓存和 single-flight 并发去重
│   │   │   └── weight_budget.py        # 进程级 Binance REST 请求权重预算
│   │   ├── coingecko/
│   │   │   ├── __init__.py             # CoinGecko integration 子包标记
│   │   │   ├── client.py               # 后台刷新 CoinGecko 市值和 FDV
│   │   │   └── store.py                # 校验、读取和保存市值缓存文件
│   │   └── storage/
│   │       ├── __init__.py             # storage 子包标记
│   │       ├── cvd_snapshot.py          # 原子保存和恢复 CVD 分钟桶
│   │       ├── file_io.py               # 安全的本地文件原子写入工具
│   │       ├── market_cache.py          # 带刷新期和最终过期时间的内存行情缓存
│   │       ├── oi_history_cache.py      # 序列化可跨重启复用的 OI 历史基准
│   │       └── oi_snapshot.py           # 读取、定时保存当前 OI 快照
│   │
│   ├── shared/                         # 跨 OI、Signal Scan、CVD 共用的后端能力
│   │   ├── __init__.py                 # shared 包标记
│   │   ├── ports/
│   │   │   ├── __init__.py             # ports 子包标记
│   │   │   └── market_data.py          # 行情数据源接口；业务只依赖契约，不依赖缓存实现
│   │   └── runtime/
│   │       ├── __init__.py             # runtime 子包标记
│   │       └── services.py              # 多服务统一 start/stop/close 和错误汇总
│   │
│   ├── static/
│   │   ├── css/
│   │   │   ├── dashboard.css           # CSS 总入口，集中导入各样式模块
│   │   │   ├── base.css                # 主题变量、重置和全局基础样式
│   │   │   ├── metrics.css             # 顶部统计卡片样式
│   │   │   ├── panels.css              # 面板、工具栏和状态区样式
│   │   │   ├── tables.css              # 表格布局、滚动和表头样式
│   │   │   ├── table-cells.css         # symbol、数值、热度等单元格样式
│   │   │   ├── signal-scan.css         # Signal Scan 标签页和表格样式
│   │   │   └── motion-responsive.css   # 动画、移动端和响应式规则
│   │   └── js/
│   │       ├── dashboard.js             # 前端组合入口，连接组件、功能和生命周期
│   │       ├── motionEffects.js         # 动态加载 Motion 并管理界面过渡动画
│   │       ├── components/
│   │       │   ├── DashboardStatus.js   # 顶部服务状态和更新时间显示
│   │       │   ├── FilterBar.js         # 搜索、数量、阈值和收藏筛选控件
│   │       │   ├── HighOi7dTable.js     # 7 日 OI 高位币种表格渲染
│   │       │   ├── MarketRowCells.js    # 两类 OI 表格共用的市场数据单元格
│   │       │   ├── MarketTooltip.js     # 行情详情浮层
│   │       │   ├── OiRankingRow.js      # 单行 OI 排名 DOM 创建与更新
│   │       │   ├── OiRankingTable.js    # OI 排名表及虚拟滚动
│   │       │   ├── OiUpdateSignal.js    # OI 数据新鲜度指示器
│   │       │   ├── SortableHeader.js    # 可点击、可键盘操作的排序表头
│   │       │   └── StatCard.js          # 统计卡片与行情连接状态渲染
│   │       ├── data/
│   │       │   ├── BinancePriceFeed.js  # 浏览器端 Binance 全市场 ticker WebSocket
│   │       │   └── DashboardElements.js # 集中获取并校验页面 DOM 节点
│   │       ├── features/
│   │       │   ├── oi/
│   │       │   │   ├── OiApiClient.js          # 请求 `/api/oi` 并处理超时、取消
│   │       │   │   ├── OiFeatureController.js  # 编排 OI 刷新、实时价格和界面更新
│   │       │   │   ├── OiPayloadSchema.js      # 校验 OI API 版本与字段结构
│   │       │   │   ├── OiRankingStore.js       # 保存排名数据并合并实时价格补丁
│   │       │   │   └── OiRefreshController.js  # OI 定时刷新、过期和重试策略
│   │       │   ├── signal-scan/
│   │       │   │   ├── SignalScanApiClient.js          # 请求并取消 Signal Scan API
│   │       │   │   ├── SignalScanPanel.js              # 多头、空头、波动榜面板渲染
│   │       │   │   ├── SignalScanPayloadSchema.js      # 校验扫描 API 版本和数据结构
│   │       │   │   └── SignalScanRefreshController.js  # Signal Scan 定时刷新策略
│   │       │   └── cvd/
│   │       │       └── format.js        # CVD 状态、健康度和数值的前端格式化
│   │       ├── hooks/
│   │       │   ├── useFavorites.js      # 收藏集合及 localStorage 持久化
│   │       │   ├── useTableFilters.js   # 表格筛选状态
│   │       │   └── useTableSort.js      # 排序字段、方向和表头状态
│   │       ├── services/
│   │       │   ├── DashboardRenderer.js       # 汇总渲染状态、统计卡和价格状态
│   │       │   ├── LiveUpdateCoordinator.js   # 根据标签页和可见性启停数据源
│   │       │   ├── PageLifecycle.js           # 页面可见性、启动和销毁生命周期
│   │       │   ├── RankingProcessor.js        # 调度 Worker 计算，失败时回退主线程
│   │       │   ├── RankingViewController.js   # 管理排名计算请求和最新视图状态
│   │       │   └── UiRenderScheduler.js       # 合并同一动画帧内的重复渲染请求
│   │       ├── utils/
│   │       │   ├── binanceTicker.js     # 解析、校验并合并 Binance ticker 消息
│   │       │   ├── dom.js               # 最小化重排的 DOM 子节点同步工具
│   │       │   ├── format.js            # 价格、百分比、时间和颜色格式化
│   │       │   ├── oiStats.js           # 从 OI 行计算顶部摘要统计
│   │       │   ├── rankingEngine.js     # 应用筛选、排序并生成排名视图
│   │       │   └── rankingRows.js       # 行情补丁、排序值和高 OI 列表计算
│   │       └── workers/
│   │           └── rankingWorker.js      # 在 Web Worker 中执行排名计算
│   └── scripts/
│       └── check-static-js.mjs          # 检查前端模块引用、语法和静态资源入口
│
├── tests/                               # Python 单元/集成测试和部分前端 Node 测试
│   ├── __init__.py                      # tests 包标记
│   ├── test_background_service.py       # 后台 poller 生命周期与异常测试
│   ├── test_batch_selector.py           # OI 循环批次选择测试
│   ├── test_binance_rest_cache.py       # 共享 REST 缓存和 single-flight 测试
│   ├── test_bootstrap.py                # 服务装配与关闭顺序测试
│   ├── test_cli.py                      # 命令行默认值和参数校验测试
│   ├── test_cvd.py                      # CVD 分钟桶、窗口和方向计算测试
│   ├── test_cvd_architecture.py         # CVD 分片、补数和容量约束测试
│   ├── test_cvd_poller.py               # CVD 主协调器行为测试
│   ├── test_http.py                     # HTTP 重试、限流、取消和解析测试
│   ├── test_live_update_coordinator.mjs # 前端实时数据启停协调测试
│   ├── test_market_cap.py               # 市值 ticker 匹配和数据映射测试
│   ├── test_market_cap_client.py        # CoinGecko 客户端刷新测试
│   ├── test_market_cap_defaults.py      # 市值功能默认配置测试
│   ├── test_market_cap_store.py         # 市值缓存文件读写和校验测试
│   ├── test_market_snapshot.py          # OI 共享行情快照测试
│   ├── test_oi_batch.py                 # OI 批量抓取和错误隔离测试
│   ├── test_oi_history_cache.py         # 历史 OI 缓存序列化测试
│   ├── test_oi_history_points.py        # 历史 OI 点解析和基准测试
│   ├── test_oi_history_service.py       # 历史 OI 加载、刷新和缓存流程测试
│   ├── test_oi_refresh_controller.mjs   # 前端 OI 定时刷新策略测试
│   ├── test_oi_row.py                   # 单行 OI 指标计算测试
│   ├── test_page_lifecycle.mjs          # 前端页面可见性和销毁测试
│   ├── test_poller_health.py            # OI 健康状态和错误记录测试
│   ├── test_presenter.py                # OI API payload 组装测试
│   ├── test_runtime.py                  # OI 线程和停止流程测试
│   ├── test_server.py                   # HTTP 路由、静态资源和 API 测试
│   ├── test_service_group.py            # 多服务统一生命周期测试
│   ├── test_signal_scan.py              # 信号规则和扫描结果测试
│   ├── test_signal_scan_api_client.mjs  # 前端扫描 API 请求和取消测试
│   ├── test_signal_scan_kline_cache.py  # 扫描 K 线 LRU 缓存测试
│   ├── test_signal_scan_klines.py       # K 线时序处理测试
│   ├── test_signal_scan_market_snapshot.py # 扫描行情快照测试
│   ├── test_signal_scan_panel.mjs       # Signal Scan 面板渲染测试
│   ├── test_signal_scan_poller.py       # 扫描调度、并发和状态发布测试
│   ├── test_signal_scan_refresh_controller.mjs # 前端扫描刷新测试
│   ├── test_signal_scan_schema.mjs      # 前端扫描 payload 校验测试
│   ├── test_snapshot_service.py         # OI 快照恢复和定时保存测试
│   └── test_symbol_refresher.py         # 合约列表刷新与防误删测试
└── tests_js/
    └── cvd.test.mjs                     # 前端 CVD 格式化测试
```

### 分层怎么理解

- `application`：后端业务流程的协调层。例如决定先抓什么、何时刷新、怎样发布结果；计算规则尽量下沉到 `domain`。
- `domain`：后端纯计算、规则和内存模型。它不依赖网页、HTTP、文件或 Binance SDK，也不是前端目录。
- `infrastructure`：与外部世界连接的实现，包括 Binance/CoinGecko、HTTP、WebSocket、缓存文件；数据结构本身应放在 `domain`。
- `shared/ports`：跨功能共用的“接口契约”。例如 OI 和 Signal Scan 只要求数据源能提供 ticker 与 exchange info，不需要知道它是直连、缓存还是假数据。
- `shared/runtime`：跨功能共用的运行期管理，例如统一启动、停止、关闭服务并收集错误。
- `static/js`：真正的浏览器前端，其中 `features` 按业务功能分组，`components`、`services`、`utils` 放多功能共用代码。

共享行情的调用关系是：`application` 依赖 `shared/ports/market_data.py` 的契约，
`infrastructure/binance/market_data.py` 提供直连实现，
`infrastructure/binance/rest_cache.py` 再为它增加进程级缓存和并发去重。



## 数据来源

- Binance Futures：合约价格、OI、成交额、资金费率和历史行情。
- CoinGecko：币种市值和完全稀释估值（FDV）。
- TradingView：图表页面。
