# CryptoExchangeTicket

生成 Binance TradingView 观察列表，并提供 Futures 实时持仓变化面板。

## 安装

需要 Python 3.10 或更高版本：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

## 生成观察列表

默认生成 Binance 现货与永续合约列表：

```bash
.venv/bin/python main.py
```

结果写入 `exchange_ticket/ticket/`，单个文件最多 500 行；重复项会自动去除，名单按交易对名称稳定排序，旧的多余分片会自动清理：

- `binance_usdt_pairs.txt`：加密货币现货
- `binance_futures_pairs.txt`：加密货币永续合约
- `binance_tradfi_spot_pairs.txt`：TradFi 现货
- `binance_tradfi_futures_pairs.txt`：TradFi 永续合约

TradFi 现货会根据当前 TradFi 期货的基础资产加 `B` 后，与实际在交易的现货自动匹配，无需维护手工名单。
现货请求和本地解析都会限定 `SPOT` 权限、`TRADING` 状态及 `isSpotTradingAllowed=true`，不会把仅保证金或杠杆权限的交易对混入现货文件。
观察列表请求遇到瞬时网络错误、限频或常见服务端错误时最多尝试 3 次，请求流程结束后会关闭独立会话。
请求失败、返回不足 10 项或缺少任一市场分类时，程序会保留全部旧文件。旧文件中超过 20% 的条目消失时，第一次运行也会保留旧文件并记录隐藏确认指纹；只有下一次独立运行得到完全相同的四份完整名单才会接受变更，少于 10 项的结果永远不能通过确认。新增条目不能掩盖大规模替换。
现货和期货的四份名单会在全部请求与校验成功后一次提交；写入或旧分片清理中途失败时，会恢复提交前的全部文件，避免出现新期货与旧现货混用。并发写入会在进程内串行；macOS/Linux 上的多个生成进程也会通过输出目录中的隐藏文件锁串行提交。20% 缩水检查会在取得锁后针对最新文件再次执行，过时的请求结果不能绕过缩水保护。
已有名单、分片、锁和确认指纹必须是普通文件；符号链接、目录、FIFO 等异常类型会被拒绝且不会被替换。

## 实时 OI 面板

```bash
.venv/bin/python -m realtime_oi_dashboard.server
```

打开 <http://127.0.0.1:8777>。浏览器通过 Binance Futures WebSocket 更新价格，服务端分批获取 OI、24 小时/7 天 OI 变化和资金费率。

如果遇到 Binance `429` 或 `418` 限频，可以降低请求速度：

```bash
.venv/bin/python -m realtime_oi_dashboard.server \
  --oi-batch-size 10 \
  --oi-batch-delay 2 \
  --oi-workers 1 \
  --ticker-cache-seconds 30
```

更多参数可用 `.venv/bin/python -m realtime_oi_dashboard.server --help` 查看。

## 前端语法检查

需要 Node.js；同时检查 JavaScript 语法、相对导入、入口可达性、样式入口以及页面 ID：

```bash
node realtime_oi_dashboard/scripts/check-static-js.mjs
```

## 目录

```text
exchange_ticket/          Binance 观察列表生成器
realtime_oi_dashboard/    实时价格和 OI 面板
shared/binance.py         Binance 符号校验和 TradingView 别名
shared/http.py            Binance JSON 请求、重试和线程会话
shared/utils.py           名单写入、数值解析和缓存原子写入
shared/web.py             OI 面板的静态文件和 JSON 响应处理
```
