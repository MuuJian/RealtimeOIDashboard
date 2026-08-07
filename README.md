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
| `--oi-history-cache-seconds` | `300` 秒 | 24 小时和 7 天 OI 历史数据的缓存时间。设为 `0` 表示不使用这层缓存。 |
| `--ticker-cache-seconds` | `10` 秒 | 24 小时行情数据的缓存时间。调大可以减少请求次数。 |
| `--funding-cache-seconds` | `3600` 秒 | 资金费率备用数据的缓存时间。 |
| `--market-cap-refresh-seconds` | `3600` 秒 | 市值和 FDV 的刷新间隔，默认每小时更新一次。 |
| `--snapshot-save-interval` | `10` 秒 | 当前 OI 状态保存到本地文件的间隔。 |
| `--signal-scan-interval` | `60` 秒 | 趋势和波动率信号重新扫描的间隔。 |

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

## 数据来源

- Binance Futures：合约价格、OI、成交额、资金费率和历史行情。
- CoinGecko：币种市值和完全稀释估值（FDV）。
- TradingView：图表页面。

## 测试

运行后端测试：

```bash
.venv/bin/python -m unittest discover -s tests -v
```

检查前端文件：

```bash
node realtime_oi_dashboard/scripts/check-static-js.mjs
```

## CVD interpretation

The OI ranking table includes a 15-minute Cumulative Volume Delta (CVD) value
and interpretation label for the 30 highest-24-hour-quote-volume USDT
perpetual contracts. CVD measures the net USDT value of taker buys minus taker
sells; it is an order-flow context signal, not a price forecast.

After startup, CVD labels show `資料累積中` until the first 15-minute window is
complete. `買盤主導` and `賣盤主導` indicate a normalized CVD imbalance of at
least +10% or -10%; smaller imbalances are `中性`. Contracts outside the
30-symbol CVD universe show `未追蹤`, while a disconnected CVD service shows
`資料不可用`. CVD columns are informational and do not filter or reorder OI
results.
