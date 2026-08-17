# Realtime OI Dashboard

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

- Binance Futures：合约价格、OI、成交额、资金费率和历史行情。
- CoinGecko：币种市值和完全稀释估值（FDV）。
- TradingView：图表页面。
