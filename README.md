# RealtimeOIDashboard

Binance Futures 实时 OI 面板。价格由浏览器 WebSocket 实时更新；Python 服务端分批轮询当前 OI、历史 OI、24 小时行情与资金费率。

WebSocket 断线或连续 15 秒没有收到有效 ticker 时，会立即撤销实时价格覆盖、恢复最近一次服务端行情并重连；重连收到新行情后再切回实时价格。
服务端 ticker 和资金费率请求失败时，只会在原定刷新时间后继续回退最多 15 分钟；超过期限会停止使用旧市场数据。缓存时间设为 `0` 时不会保留响应，也不会回退。

## 安装

需要 Python 3.10 或更高版本：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

## 代码结构

- `main.py`：项目根目录启动入口。
- `realtime_oi_dashboard/cli.py`：命令行参数与 Railway 环境变量默认值。
- `realtime_oi_dashboard/server.py`：HTTP 服务、轮询线程与启动/停止流程。
- `realtime_oi_dashboard/poller.py`：合约刷新、批次轮询、OI 状态与运行生命周期。
- `realtime_oi_dashboard/oi_batch.py`：单币种 OI 行计算与并行批处理。
- `realtime_oi_dashboard/poller_health.py`：近期错误与系统时钟连续性状态。
- `realtime_oi_dashboard/binance_client.py`：Binance Futures 请求和市场缓存协调。
- `realtime_oi_dashboard/market_cap_client.py`：CoinGecko 分页、市值缓存与失败回退。
- `realtime_oi_dashboard/http.py`：多线程安全的 JSON 请求与重试。
- `realtime_oi_dashboard/market_cache.py`：ticker 与资金费率缓存状态。
- `realtime_oi_dashboard/market_data.py`：实时行情与资金费率响应解析。
- `realtime_oi_dashboard/oi_history_points.py`：历史 OI 数据点解析与变化计算。
- `realtime_oi_dashboard/oi_history.py`：历史 OI 基线选择、缓存与变化计算。
- `realtime_oi_dashboard/oi_history_cache.py`：历史基线的重启缓存编解码。
- `realtime_oi_dashboard/oi_state.py`：同步维护页面行及其更新时间。
- `realtime_oi_dashboard/snapshot_store.py`：持久化合约集合和历史基线缓存。
- `realtime_oi_dashboard/file_io.py`：缓存文件原子写入。
- `realtime_oi_dashboard/parsing.py`：严格数值解析。
- `realtime_oi_dashboard/market_cap.py`：Binance 合约代码与 CoinGecko 币种的匹配逻辑。
- `realtime_oi_dashboard/symbols.py`：Binance 合约名称校验。
- `realtime_oi_dashboard/web.py`：静态文件与 JSON 响应处理。
- `realtime_oi_dashboard/static/js/data/`：价格 WebSocket、OI API 契约与排行数据仓库。
- `realtime_oi_dashboard/static/js/components/`：表格、筛选器、提示框与状态卡渲染。
- `realtime_oi_dashboard/static/js/services/`：页面生命周期、OI 刷新、排行 Worker、视图协调与 UI 调度。
- `realtime_oi_dashboard/static/js/hooks/`：收藏、筛选和排序状态。
- `realtime_oi_dashboard/static/js/utils/`：格式化、排行计算与 OI 统计等纯函数。

页面会从 jsDelivr 按固定版本加载 Motion；加载失败时自动保留完整功能并退回无 Motion 动效。页面使用纯黑底色和不透明的中性黑灰面板，不创建全屏 Canvas 粒子、背景光团或毛玻璃效果。标签页不可见或所在窗口失去焦点时只暂停 CSS 与 Motion 动画，价格 WebSocket 和 OI 定时刷新保持运行；重新切回 OI 页面时还会立即补一次 OI 刷新。系统开启“减少动态效果”后也会停用进入和表格行级动画。

## 启动

在仓库根目录运行：

```bash
.venv/bin/python main.py
```

打开 <http://127.0.0.1:8777>。

公网托管时会自动读取平台提供的 `PORT` 环境变量，并监听
`0.0.0.0:$PORT`。Railway 的 Start Command 可以直接填写：

```bash
python main.py
```

也可以显式指定：`python main.py --host 0.0.0.0 --port "$PORT"`。

默认每批更新 25 个交易对，批次之间等待 1 秒，并使用 3 个 OI worker。资金费率正常情况下会在 Binance 返回的下一次结算时间后刷新；`--funding-cache-seconds` 只在结算时间缺失时作为兜底，已经过去的结算时间不会继续显示。

市值数据来自 CoinGecko 公开 API 按市值排名前 1250 名的币种（`--market-cap-cache-seconds` 控制缓存时长，默认 900 秒），按 Binance 合约代码去除倍数前缀与 `USDT` 后缀后与 CoinGecko 币种代码匹配；主排行同时展示原始市值和“持仓价值 ÷ 市值”的百分比，两列均可排序，排名更靠后或匹配不到时显示 `-`。CoinGecko 该接口对匿名请求的限流很严格，实测无论请求间隔多长，连续第 6 页请求必定被限流，因此固定只请求 5 页；单页请求失败时保留已抓到的前几页数据，不会因为最后一页限流就整批作废，也不会阻塞或减慢 OI 轮询；下次缓存到期后重新尝试完整抓取。

限频时可以降速：

```bash
.venv/bin/python main.py \
  --oi-batch-size 10 \
  --oi-batch-delay 2 \
  --oi-workers 1 \
  --ticker-cache-seconds 30
```

页面只显示本次启动后刚获取的数据，并按批次逐步填充。默认每批轮询 25 个交易对，批次完成后等待 1 秒；约 530 个交易对完整一轮至少需要二十多秒，实际还要加上接口耗时。缓存文件默认每 10 秒原子写入 `realtime_oi_dashboard/data/latest_oi.json`，只保存最后一次完整合约集合和仍在有效期内的 24 小时/7 天历史基线，不保存或立即显示旧页面行。短时间重启会复用未过期的历史基线，减少对 Binance 历史接口的重复请求。可用 `--snapshot-save-interval` 调整间隔，正常停止时还会保存一次最后完成的批次。损坏、嵌套过深或异常超过 5 MiB 的缓存会被忽略，并在新数据到达后重建，不会阻断服务启动。

单个合约短暂更新失败时会保留最后一行，避免页面闪烁；连续 15 分钟没有成功更新时，该行会自动清理，恢复成功后重新出现。合约名称仍会保留在独立集合中，仅用于名单缩水检查。
每个合约的有效期从其当前 OI 响应到达时单独计算；同批其他合约的慢请求或历史 OI 重试不会延长这 15 分钟。
如果本地服务无法访问，或后台 OI 轮询线程意外停止，浏览器会在连续异常 15 分钟后清空旧行，而不是无限保留最后一次画面。
标签页不可见或所在窗口失去焦点时只暂停页面动画，价格 WebSocket 和 OI 请求会继续更新；重新显示或获得焦点后会立即补一次 OI 刷新。
电脑休眠或系统时间明显跳变后，服务端会清空易过期的行、市场行情和历史 OI 缓存，保留已知合约集合并重新分批获取，避免把休眠前的数据继续当成实时数据。
API 返回数据前还会独立检查最近成功批次的墙上时钟时间；即使系统休眠期间单调时钟没有推进，超过 15 分钟的内存行也不会重新显示。

合约名单默认每 15 分钟刷新。刷新请求失败或返回的名单异常缩水时，服务会继续使用当前名单轮询，并在 60 秒后重试，不会立即删除大量现有数据；如果同一份大幅缩减名单连续两次返回，则把它视为已确认变更并接受，避免长期停机后的旧名单永久阻断启动。
合约确认下架后，服务端会从页面数据和缓存中移除它，浏览器也会根据完整活跃合约名单同步删除对应的本地收藏；服务刚启动或合约名单请求异常时不会清空收藏。

24 小时和 7 天变化按历史记录的真实时间戳匹配。价格(7d%)使用同一条 7 天 OI 历史记录中的持仓价值除以持仓数量得到历史价格，不会增加单独的 K 线请求；当前端 WebSocket 价格变化时会实时重算。历史基线缓存不会超过来源点剩余的两小时容差；到期后即使配置了更长缓存也会重新请求。历史接口短暂失败时，只会回退仍在容差内的基线；超出范围就显示 `-`，不会无限复用旧数据或用错误跨度代替。

主排行表使用固定行高的虚拟滚动，只创建当前视口附近的行；排序、筛选、收藏和实时价格更新仍作用于完整数据集。

上方 7D OI 异动信号可切换最低 7 天 OI 变化和最低持仓价值。两张表使用类似自动减仓指示器的五格灯显示 OI 新鲜度：20 秒内为 1 格绿色，超过 20 秒且不足 1 分钟为 3 格黄色，满 1 分钟后为 5 格红色；15 分钟未成功更新仍会按服务端规则移除。悬停合约行仍可查看具体相对更新时间。

悬停任意合约行会显示完整行情、OI 与更新时间详情。主排行的排序字段和升降序保存在当前浏览器中，刷新页面后继续沿用。

浏览器端价格流与页面渲染分离：Binance WebSocket 先在独立数据源中合并同一帧的 ticker，再发布批次更新；OI 定时请求和过期判断由独立刷新控制器管理；筛选、排序、高 OI 信号和热力范围由 Web Worker 计算，Worker 不可用时自动回退主线程。UI 使用独立调度器合并到单一 `requestAnimationFrame` 队列提交更新，两张表共用同一套行情单元格并复用已有行节点，不通过 `innerHTML` 重建。

## 前端检查

无需安装前端依赖，在仓库根目录运行：

```bash
node realtime_oi_dashboard/scripts/check-static-js.mjs
```
