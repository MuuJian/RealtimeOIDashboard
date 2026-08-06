# Realtime OI Dashboard

监控 **Binance USDT 永续合约** 的实时数据面板。

> 本项目只提供市场数据展示，不构成投资建议。

## 安装

需要 Python 3.10 或更高版本。

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

## 启动

在仓库根目录运行：

```bash
.venv/bin/python main.py
```

然后在浏览器打开：

```text
http://127.0.0.1:8777
```

## 公网部署

程序会自动读取托管平台提供的 `PORT` 环境变量，并监听：

```text
0.0.0.0:$PORT
```

常见的启动命令：

```bash
python main.py
```

也可以显式指定：

```bash
python main.py --host 0.0.0.0 --port "$PORT"
```

## 常用参数

网络受限或 Binance 请求频率过高时，可以降低 OI 请求速度：

```bash
.venv/bin/python main.py \
  --oi-batch-size 10 \
  --oi-batch-delay 2 \
  --oi-workers 1 \
  --ticker-cache-seconds 30
```

主要参数：

| 参数 | 作用 | 默认值 |
|---|---|---:|
| `--oi-batch-size` | 每批更新的合约数量 | `25` |
| `--oi-batch-delay` | 每批请求之间的等待秒数 | `1` |
| `--oi-workers` | 并行 OI 请求数量 | `3` |
| `--ticker-cache-seconds` | 24 小时行情缓存时间 | `10` |
| `--funding-cache-seconds` | 资金费率缓存时间 | `3600` |
| `--market-cap-refresh-seconds` | CoinGecko 市值刷新间隔 | `3600` |
| `--snapshot-save-interval` | 本地快照保存间隔 | `10` |
| `--signal-scan-interval` | 訊號掃描刷新间隔 | `60` |

## 项目结构

### 整体架构

系统由三条相互独立的数据链路组成：

```text
主 OI 链路（服务端）
Binance Futures REST + CoinGecko
        ↓
OIPoller → OIStateStore → DashboardPresenter → /api/oi
        ↓
本地 OI 历史快照

实时价格链路（浏览器）
Binance Futures WebSocket → BinancePriceFeed → 排名计算 → 主 OI 面板

訊號掃描链路（独立服务端线程）
Binance Futures REST → SignalScanPoller → /api/signal-scan → 訊號面板
```

`server.py` 是应用的组合入口。启动时会创建 HTTP 服务、主 OI 轮询器和可选的訊號掃描轮询器；两种轮询分别运行在线程中，HTTP 请求只读取已经准备好的内存状态，不会在请求期间现场抓取全部市场数据。

### 主 OI 更新流程

每轮更新由 `DashboardRuntime` 驱动，`OIPoller` 作为 Facade 协调以下步骤：

1. `SymbolRefresher` 定期从 Binance 刷新有效的 USDT 永续合约，并清理已下架合约的数据。
2. `MarketSnapshotProvider` 为本轮统一准备 ticker、资金费率和市值快照。
3. `RoundRobinBatchSelector` 按原始顺序循环选择下一批合约。
4. `OIBatchRunner` 使用固定大小的线程池并行请求 OI；单个合约失败只记录错误，不中断整批数据。
5. `OIRowBuilder` 组装 API 行，`OIStateStore` 原子替换已成功更新的行。
6. `SnapshotService` 按保存间隔将合约列表和 OI 历史缓存原子写入本地文件，供重启后恢复。
7. `DashboardPresenter` 在 `/api/oi` 请求到达时生成字段稳定的公开数据，并过滤过期行。

CoinGecko 市值刷新在单独的后台线程中运行，不阻塞主 OI 更新。系统检测到休眠、时钟跳变或数据超过 15 分钟未更新时，会丢弃不可信的临时数据并等待重新获取。

### 訊號掃描与故障隔离

`SignalScanPoller` 拥有独立的线程、状态和 `/api/signal-scan` 接口。它负责获取 1 小时 K 线并计算多头趋势、空头趋势及波动率突增结果。

訊號掃描在创建、启动或运行期间失败时，主 OI 轮询和 `/api/oi` 会继续服务；訊號接口会单独返回不可用状态。关闭程序时，两条轮询链路也会分别停止和释放资源。

### 前端数据流

- `OiRefreshController` 每 10 秒读取 `/api/oi`，更新主 OI 数据和服务状态。
- `BinancePriceFeed` 在浏览器直接连接 Binance Futures WebSocket，合并实时价格后只更新受影响的行。
- `RankingProcessor` 优先在 Web Worker 中完成筛选、排序、热度和高 OI 排名计算；Worker 不可用时自动回退到主线程计算。
- `UiRenderScheduler` 与 `DashboardRenderer` 合并同一帧内的渲染请求，并区分整表渲染和单行更新。
- `SignalScanRefreshController` 只在打开訊號扫描页时轮询 `/api/signal-scan`，与主 OI 刷新控制器互不依赖。
- 收藏列表保存在浏览器 `localStorage`；收到经过验证的有效合约列表后，前端会同步清理已下架合约。

### 并发与状态边界

| 组件 | 运行位置 | 主要职责 |
|---|---|---|
| `DashboardHTTPServer` | 服务端 HTTP 线程 | 静态资源及两个只读 JSON API |
| `DashboardRuntime` | 主 OI 轮询线程 | 调度批次、错误恢复和停止流程 |
| `OIBatchRunner` | 固定线程池 | 并行更新单个合约 OI |
| `CoinGeckoMarketCapClient` | 市值后台线程 | 独立刷新市值缓存 |
| `SignalScanPoller` | 独立扫描线程 | 计算并发布訊號扫描结果 |
| `BinancePriceFeed` | 浏览器 | 接收实时价格 WebSocket |
| `RankingProcessor` | 浏览器 Web Worker | 排名、筛选和统计计算 |

共享的服务端内存状态通过锁保护；磁盘快照采用临时文件替换，避免留下半写入文件。对外 API 只暴露 Presenter 和扫描器生成的状态，不直接泄露内部缓存对象。

### 目录与职责

```text
main.py
realtime_oi_dashboard/
├── cli.py
├── server.py
├── web.py
├── signal_scan.py
├── domain/
│   ├── market_data.py
│   ├── market_cap.py
│   ├── oi_history_points.py
│   ├── oi_row.py
│   └── oi_state.py
├── application/
│   ├── poller.py
│   ├── symbol_refresher.py
│   ├── batch_selector.py
│   ├── market_snapshot.py
│   ├── oi_batch.py
│   ├── presenter.py
│   └── runtime.py
├── infrastructure/
│   ├── binance_client.py
│   ├── market_cap_client.py
│   ├── market_cap_store.py
│   ├── snapshot_store.py
│   └── http.py
├── index.html
├── static/
└── data/
tests/
```

主要模块：

- `main.py`：程序入口
- `cli.py`：启动参数和环境变量
- `server.py`：HTTP 服务及程序生命周期
- `web.py`：静态资源与 JSON 响应的通用 HTTP 处理
- `signal_scan.py`：独立计算并保存趋势与波动率訊號
- `domain/`：不依赖网络和文件系统的市场规则、计算与数据结构
- `application/`：轮询、批次、状态和 API 展示的业务编排
- `infrastructure/`：Binance、CoinGecko、HTTP 与 JSON 存储适配器
- `static/`：前端页面、JavaScript 和 CSS
- `tests/`：后端单元测试

核心调用关系：

```text
server.py
   ↓
OIPoller (Facade)
   ├─ SymbolRefresher
   ├─ RoundRobinBatchSelector
   ├─ MarketSnapshotProvider
   ├─ OIBatchRunner → OIRowBuilder
   ├─ OIStateStore
   ├─ SnapshotService → SnapshotRepository
   ├─ DashboardPresenter
   └─ DashboardRuntime
```

这些拆分只调整内部职责；`/api/oi` 字段、轮询顺序、计算方式、
缓存规则和前端行为保持不变。

## 测试

运行后端测试：

```bash
.venv/bin/python -m unittest discover -s tests -v
```

运行前端静态检查：

```bash
node realtime_oi_dashboard/scripts/check-static-js.mjs
```

## 数据来源

- Binance Futures：价格、OI、成交量、资金费率及历史数据
- CoinGecko：币种市值和 FDV
- TradingView: 图表
