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

## 项目结构

```text
main.py
realtime_oi_dashboard/
├── cli.py
├── server.py
├── poller.py
├── binance_client.py
├── symbol_refresher.py
├── batch_selector.py
├── market_snapshot.py
├── market_cap_client.py
├── market_cap_store.py
├── oi_batch.py
├── oi_row.py
├── oi_state.py
├── snapshot_store.py
├── presenter.py
├── runtime.py
├── oi_history.py
├── static/
└── data/
tests/
```

主要模块：

- `main.py`：程序入口
- `cli.py`：启动参数和环境变量
- `server.py`：HTTP 服务及程序生命周期
- `poller.py`：对外兼容的 Facade，协调一次 OI 更新流程
- `binance_client.py`：请求 Binance Futures 数据
- `symbol_refresher.py`：刷新并维护有效合约列表
- `batch_selector.py`：按原顺序循环选择下一批合约
- `market_snapshot.py`：每轮统一获取 ticker、funding 和市值快照
- `market_cap_client.py`：后台获取 CoinGecko 市值
- `market_cap_store.py`：读取和保存市值 JSON
- `oi_batch.py`：以固定线程数请求 OI，并隔离单币失败
- `oi_row.py`：把已获取的数据组装成稳定的 API row
- `oi_state.py`：管理页面行和数据更新时间
- `snapshot_store.py`：原子读写 OI 快照，并控制保存频率
- `presenter.py`：生成字段稳定的 `/api/oi` 返回数据
- `runtime.py`：管理轮询线程、后台市值任务和停止流程
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
