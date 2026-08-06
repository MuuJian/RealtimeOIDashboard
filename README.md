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

### 目录与职责

```text
main.py
realtime_oi_dashboard/
├── bootstrap.py
├── cli.py
├── server.py
├── web.py
├── domain/
│   ├── market_data.py
│   ├── market_cap.py
│   ├── oi_history_points.py
│   ├── oi_row.py
│   ├── oi_state.py
│   └── signal_scan.py
├── application/
│   ├── poller.py
│   ├── background_service.py
│   ├── symbol_refresher.py
│   ├── batch_selector.py
│   ├── market_snapshot.py
│   ├── oi_batch.py
│   ├── presenter.py
│   ├── runtime.py
│   └── signal_scan.py
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
- `bootstrap.py`：组装并管理 HTTP 服务、OI 和 Signal Scan 的生命周期
- `cli.py`：启动参数和环境变量
- `server.py`：只负责 HTTP 路由，并通过注入的状态提供者返回数据
- `web.py`：静态资源与 JSON 响应的通用 HTTP 处理
- `domain/`：不依赖网络和文件系统的市场规则、计算与数据结构
- `application/`：轮询、批次、状态和 API 展示的业务编排
- `infrastructure/`：Binance、CoinGecko、HTTP 与 JSON 存储适配器
- `static/`：前端页面、JavaScript 和 CSS
- `tests/`：后端单元测试


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
