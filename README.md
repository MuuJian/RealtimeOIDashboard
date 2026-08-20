# Realtime OI Dashboard

## OI 告警 Telegram 设置

1. 在 Telegram 中打开 `@BotFather`，发送 `/newbot` 创建机器人。
2. 打开与新机器人的私聊并发送 `/start`，或者将机器人加入接收告警的群组。
3. 向机器人私聊或目标群组发送一条消息后，在 PowerShell 中运行以下命令获取聊天 ID：
   ```powershell
   $updates = Invoke-RestMethod "https://api.telegram.org/bot$env:TELEGRAM_BOT_TOKEN/getUpdates"
   $updates.result[-1].message.chat.id
   ```
   将返回值设置为 `TELEGRAM_CHAT_ID`；群组 ID 通常为负数。
4. 在启动 `main.py` 的运行环境中设置 `TELEGRAM_BOT_TOKEN` 和 `TELEGRAM_CHAT_ID`。
5. 打开面板中的 OI 告警页面，先点击“發送測試訊息”确认配置正常，再启用实时通知。

面板不会把这两个敏感值写入配置文件，也不会通过 API 响应返回。OI 告警只发送通知，绝不会自动下单。

## 安装

需要 Python 3.10 或更高版本。前端检查需要 Node.js 22 或更高版本和 npm 10 或更高版本。

在项目目录中运行：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

如果需要运行前端测试和静态检查，再安装 Node.js 依赖：

```bash
npm ci
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

完成依赖安装后，可以用一条命令执行与 CI 相同的依赖一致性检查、后端测试、前端测试和静态检查：

```bash
.venv/bin/python -m pip check && .venv/bin/python -m unittest discover -s tests -v && npm test
```

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
| 后端计算使用的价格、价格(24h)、成交额(24h) | Binance REST `/fapi/v1/ticker/24hr` | OI 与 Signal Scan 共用唯一一层内存缓存，固定10秒；不提供启动参数。 |
| 当前 OI | Binance REST `/fapi/v1/openInterest` | 每个币进入 OI 更新批次时请求一次。 |
| 持仓(24h)、持仓(7d) | Binance REST `/futures/data/openInterestHist?period=1h&limit=169` | 每个币约一小时请求一次；同一次响应同时计算24h和7d，不是两个请求。只缓存在内存，服务重启后重新获取。 |
| 价格(7d) | 同一个 `/futures/data/openInterestHist` 响应 | 使用7天前的 `sumOpenInterestValue ÷ sumOpenInterest` 推算历史价格，再与当前价格比较；不是K线收盘价。 |
| 资金费率 | Binance REST `/fapi/v1/premiumIndex` | 按资金费率时间刷新；`--funding-cache-seconds` 只控制备用缓存。 |
| Signal Scan 趋势与波动 | Binance REST `/fapi/v1/klines?interval=1h` | 默认每60秒扫描，首次取120根1小时K线，之后优先增量更新。 |
| CVD | Binance Futures WebSocket `<symbol>@kline_1m` | 使用1分钟成交数据实时累计；缺失分钟通过 REST `/fapi/v1/klines` 补齐。CVD 自己的快照参数与 OI 无关。 |
| 市值与 FDV | CoinGecko `/api/v3/coins/markets` | 默认每小时刷新，由 `--market-cap-refresh-seconds` 控制。 |


## OI Alerts Telegram

1. Open @BotFather in Telegram and create a bot with /newbot.
2. Start a private chat with the new bot using /start, or add it to the destination group.
3. After sending the bot (or destination group) a message, retrieve the chat ID with PowerShell:
   ```powershell
   $updates = Invoke-RestMethod "https://api.telegram.org/bot$env:TELEGRAM_BOT_TOKEN/getUpdates"
   $updates.result[-1].message.chat.id
   ```
   Use the returned value as `TELEGRAM_CHAT_ID` (group IDs are commonly negative).
4. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in the environment that starts main.py.
5. Open OI Alerts and select Send test message before enabling live delivery.

The dashboard stores neither secret in configuration files nor API responses. OI alert signals are notification-only and never place exchange orders.

一个用于查看 **Binance USDT 永续合约** 行情、持仓量（OI）变化和市场信号的网页面板。
