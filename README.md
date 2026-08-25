# Realtime OI Dashboard

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

`main` 同时支持 `full` 和 `stable` 两种运行配置，默认使用 `full`。

完整版本会启用 OI、CVD、Signal Scan 和 OI Alerts：

```bash
.venv/bin/python main.py --profile full
```

稳定版本只启用 OI，不会启动 CVD、Signal Scan 和 OI Alerts，对应页面和 API 也不会开放：

```bash
.venv/bin/python main.py --profile stable
```

不填写 `--profile` 时等同于 `--profile full`。

```
http://127.0.0.1:8777
```

部署时也可以通过环境变量选择配置：

```bash
DASHBOARD_PROFILE=stable .venv/bin/python main.py
```

完整版本对应 `DASHBOARD_PROFILE=full`。命令行的 `--profile` 会覆盖环境变量。

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
| `--profile` | `full` | `full` 启用完整功能；`stable` 只启用 OI。也可以通过 `DASHBOARD_PROFILE` 环境变量设置。 |
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

## Signal Scan 与 OI 警报

两个页面共用同一份后端 OI 特征，不会各自重复请求 Binance：

- **Signal Scan** 先用 1 小时 K 线筛选趋势与波动率，再补充同一标的的短窗口 OI 数量变化、价格变化、15 分钟 CVD、资金费率和判读原因。页面刚启动时需要先积累完整窗口，因此 OI 窗口列可能暂时显示 `-`。
- **OI 警报** 把“方向信号”和“绝对规模”分开。方向信号使用 OI 合约数量变化判断真实扩仓，再用价格方向分类为多头扩仓、空头扩仓或方向未确认；绝对 OI 美元价值只表示仓位规模，不再解释为开多或加仓。
- Signal Scan 的“加入监控”只会把交易对填入 OI 警报监控清单，并跳转到规则页面供确认；点击“储存门槛”后规则才会生效。
- 方向信号采用回落解除、同币冷却和单次触发，避免每批 OI 更新重复通知。绝对规模一次跨过多个门槛时只生成最高级别的一条事件。
- 特征时间、警报时间和面板中的 OI 更新时间优先使用 Binance 响应里的交易所时间；页面右上角的实时时钟仍是本地当前时间。

OI 警报页面可设置：

| 设置 | 默认值 | 作用 |
|---|---:|---|
| 方向信号通知 | 开启 | 控制 OI 扩仓方向事件是否发送 Telegram。 |
| 绝对 OI 规模提醒 | 开启 | 控制 3 档 OI 美元规模越线事件和对应的当前规则列表。 |
| 监控币种 | 全部 | 留空监控全部 USDT 永续；填写时只监控清单中的交易对。 |
| OI/价格比较窗口 | 15 分钟 | 使用窗口前后的 OI 合约数量与价格计算变化。 |
| 最小 OI 数量变化 | 3% | 达到该扩仓幅度后才进入方向判读。 |
| 最小价格变化 | 0.5% | 价格达到正阈值为多头扩仓，达到负阈值为空头扩仓，否则方向未确认。 |
| 同币冷却时间 | 30 分钟 | 同一交易对两次方向通知的最短间隔。 |
| 要求 CVD 数据 | 关闭 | 开启后，没有 CVD 数据时不触发方向事件；CVD 与价格方向相反时标记为方向未确认。 |
| 绝对规模门槛 | 75M / 100M / 150M USD | 三档中性 OI 规模提醒，必须保持递增。 |


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

面板不会把这两个敏感值写入配置文件，也不会通过 API 响应返回。OI 告警只发送通知，绝不会自动下单。通知会先写入事件记录再进入后台发送队列；程序重启时会重新投递尚未完成的事件，因此采用至少一次发送语义，极端断电场景可能出现一条重复消息。
