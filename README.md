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
├── market_cap_client.py
├── market_cap_store.py
├── oi_batch.py
├── oi_state.py
├── oi_history.py
├── static/
└── data/
tests/
```

主要模块：

- `main.py`：程序入口
- `cli.py`：启动参数和环境变量
- `server.py`：HTTP 服务及程序生命周期
- `poller.py`：协调 OI、历史数据、市值和缓存
- `binance_client.py`：请求 Binance Futures 数据
- `market_cap_client.py`：后台获取 CoinGecko 市值
- `market_cap_store.py`：读取和保存市值 JSON
- `oi_batch.py`：并行处理 OI 批次
- `oi_state.py`：管理页面行和数据更新时间
- `static/`：前端页面、JavaScript 和 CSS
- `tests/`：后端单元测试

## 测试

运行后端测试：

```bash
python3 -m unittest discover -s tests -v
```

运行前端静态检查：

```bash
node realtime_oi_dashboard/scripts/check-static-js.mjs
```

## 数据来源

- Binance Futures：价格、OI、成交量、资金费率及历史数据
- CoinGecko：币种市值和 FDV
- TradingView: 图表
