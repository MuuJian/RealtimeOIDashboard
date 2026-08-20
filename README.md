# Realtime OI Dashboard

一个用于查看 **Binance USDT 永续合约** 行情和持仓量（OI）变化的网页面板。

## 安装

需要 Python 3.10 或更高版本。前端检查需要 Node.js 22 或更高版本和 npm 10 或更高版本，不需要安装 pnpm，也没有需要下载的前端依赖。

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

正常使用不需要修改这些参数。需要调整访问方式或后台更新速度时，可以在启动命令后面添加：

| 参数 | 默认值 | 作用 |
|---|---:|---|
| `--host` | `127.0.0.1` | 面板监听地址。只在当前电脑访问时保持默认；需要让同一网络里的手机访问时使用 `0.0.0.0`。 |
| `--port` | `8777` | 面板使用的端口。端口被其他程序占用时可以更换。 |
| `--oi-batch-size` | `25` | 每批更新的合约数量。调小会降低单批请求量，但完成全部更新需要更久。 |
| `--oi-batch-delay` | `1` 秒 | 两批 OI 请求之间的等待时间。网络不稳定或请求过快时可以调大。 |
| `--oi-workers` | `3` | 同时发送的 OI 请求数量。调小可以降低请求压力。 |
| `--funding-cache-seconds` | `3600` 秒 | 资金费率备用数据的缓存时间。 |
| `--market-cap-refresh-seconds` | `3600` 秒 | 市值和 FDV 的刷新间隔，默认每小时更新一次。 |

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

运行全部前端测试和静态检查：

```bash
npm test
```

只运行静态检查：

```bash
npm run lint
```

## 数据来源

下面这张表用来区分“页面更新频率”“后端请求频率”和“缓存时间”。它们不是一回事。

| 页面数据 | 数据接口 | 更新与缓存方式 |
|---|---|---|
| 浏览器实时价格、价格(24h)、成交额(24h) | Binance Futures WebSocket `!ticker@arr` | 浏览器直接接收实时推送，不经过后端10秒缓存。断线时自动重连。 |
| 后端计算使用的价格、价格(24h)、成交额(24h) | Binance REST `/fapi/v1/ticker/24hr` | OI 使用唯一一层内存缓存，固定10秒；不提供启动参数。 |
| 当前 OI | Binance REST `/fapi/v1/openInterest` | 每个币进入 OI 更新批次时请求一次。 |
| 持仓(24h)、持仓(7d) | Binance REST `/futures/data/openInterestHist?period=1h&limit=169` | 每个币约一小时请求一次；同一次响应同时计算24h和7d，不是两个请求。只缓存在内存，服务重启后重新获取。 |
| 价格(7d) | 同一个 `/futures/data/openInterestHist` 响应 | 使用7天前的 `sumOpenInterestValue ÷ sumOpenInterest` 推算历史价格，再与当前价格比较；不是K线收盘价。 |
| 资金费率 | Binance REST `/fapi/v1/premiumIndex` | 按资金费率时间刷新；`--funding-cache-seconds` 只控制备用缓存。 |
| 市值与 FDV | CoinGecko `/api/v3/coins/markets` | 默认每小时刷新，由 `--market-cap-refresh-seconds` 控制。 |

### 三个容易混淆的时间

```text
前端实时价格       = Binance WebSocket 持续推送
后端 ticker 缓存   = 固定10秒，只减少 REST 重复请求
历史 OI 基准缓存   = 约1小时，只存在运行内存
```

项目不再保存 OI 历史基准 JSON 快照。重新部署或重启后，后端会按批次重新获取历史 OI；这不会改变计算公式，只会让刚启动时的24h/7d数据逐步恢复。

TradingView 只用于打开外部图表页面，不参与面板数值计算。
