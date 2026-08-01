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
- `realtime_oi_dashboard/cli.py`：命令行参数与公网托管环境变量默认值。
- `realtime_oi_dashboard/server.py`：HTTP 服务、轮询线程与启动/停止流程。
- `realtime_oi_dashboard/poller.py`：并列协调 Binance 与 CoinGecko 客户端、批次轮询、OI 状态与运行生命周期。
- `realtime_oi_dashboard/oi_batch.py`：单币种 OI 行计算与并行批处理。
- `realtime_oi_dashboard/poller_health.py`：近期错误与系统时钟连续性状态。
- `realtime_oi_dashboard/binance_client.py`：Binance Futures 请求和市场缓存协调。
- `realtime_oi_dashboard/market_cap_client.py`：CoinGecko 后台渐进分页、限流退避与市值合并。
- `realtime_oi_dashboard/market_cap_store.py`：市值 JSON 缓存校验与原子写入。
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
- `realtime_oi_dashboard/static/css/dashboard.css`：样式统一入口，按原有级联顺序加载 CSS 模块。
- `realtime_oi_dashboard/static/css/base.css`：主题变量、页面骨架、页头与连接状态。
- `realtime_oi_dashboard/static/css/metrics.css`：顶部指标卡。
- `realtime_oi_dashboard/static/css/panels.css`：面板、工具栏和筛选控件。
- `realtime_oi_dashboard/static/css/tables.css`：表格容器、虚拟行、表头与排序控件。
- `realtime_oi_dashboard/static/css/table-cells.css`：币种、收藏、热力、更新信号和提示框。
- `realtime_oi_dashboard/static/css/motion-responsive.css`：动画、移动端布局和减少动态效果适配。
- `tests/`：命令行参数、市值匹配、OI 批处理、历史基线缓存与轮询健康状态测试。

页面会从 jsDelivr 按固定版本加载 Motion；加载失败时自动保留完整功能并退回无 Motion 动效。页面使用纯黑底色和不透明的中性黑灰面板，不创建全屏 Canvas 粒子、背景光团或毛玻璃效果。标签页不可见或所在窗口失去焦点时只暂停 CSS 与 Motion 动画，价格 WebSocket 和 OI 定时刷新保持运行；重新切回 OI 页面时还会立即补一次 OI 刷新。系统开启“减少动态效果”后也会停用进入和表格行级动画。

## 启动

在仓库根目录运行：

```bash
.venv/bin/python main.py
```

打开 <http://127.0.0.1:8777>。

公网托管时会自动读取平台提供的 `PORT` 环境变量，并监听
`0.0.0.0:$PORT`。Start Command 可以直接填写：

```bash
python main.py
```

也可以显式指定：`python main.py --host 0.0.0.0 --port "$PORT"`。

默认每批更新 25 个交易对，批次之间等待 1 秒，并使用 3 个 OI worker。资金费率正常情况下会在 Binance 返回的下一次结算时间后刷新；`--funding-cache-seconds` 只在结算时间缺失时作为兜底，已经过去的结算时间不会继续显示。

市值数据来自 CoinGecko 公开 API，并由独立后台线程渐进抓取市值排名前 2000 名的币种。后台每次只请求一页，每页最多 250 个币种，页与页之间默认等待 30 秒；遇到限流或临时网络错误时会按指数退避重试同一页，连续失败后保留该页已有数据并继续后续页面。一次完整轮次结束后默认每 1 小时重新开始，可用 `--market-cap-refresh-seconds` 调整；旧参数名 `--market-cap-cache-seconds` 仍兼容。

每个成功匹配的估值会立即合并并原子写入 `realtime_oi_dashboard/data/market_caps.json`。单页失败不会清空其他页或上一次成功值，进程重启时也会先读取这份 JSON；确认下架的合约才会从缓存删除。页面顶部的实时 OI 状态会同时显示“市值已加载数量 / 当前合约总数”，便于观察后台渐进抓取进度。OI 轮询只读取当前估值快照，不发起 CoinGecko 请求，因此 CoinGecko 限流和重试不会拖慢实时 OI 批次。Binance 合约代码会先去除倍数前缀与 `USDT` 后缀再匹配 CoinGecko 币种代码；同代码冲突时保留市值排名更高的 CoinGecko 项目。每个币种优先使用流通市值，没有流通市值时回退到 FDV，两者都没有、排名超过前 2000 或代码无法匹配时显示 `-`。主排行同时展示该估值和“持仓价值 ÷ 估值”的百分比，两列均可排序。

Railway 的 Deploy Logs 会记录每一页 CoinGecko 市值请求的成功或失败、该页匹配数量和当前累计加载数量；每轮结束后还会列出失败页与仍然缺少市值的 Binance 合约代码。完整 8 页均成功时，剩余缺失项通常表示币种不在 CoinGecko 市值前 2000，或 Binance 与 CoinGecko 的代码无法直接匹配。

限频时可以降速：

```bash
.venv/bin/python main.py \
  --oi-batch-size 10 \
  --oi-batch-delay 2 \
  --oi-workers 1 \
  --ticker-cache-seconds 30
```

页面只显示本次启动后刚获取的 OI 数据，并按批次逐步填充。默认每批轮询 25 个交易对，批次完成后等待 1 秒；约 530 个交易对完整一轮至少需要二十多秒，实际还要加上接口耗时。OI 缓存文件默认每 10 秒原子写入 `realtime_oi_dashboard/data/latest_oi.json`，只保存最后一次完整合约集合和仍在有效期内的 24 小时/7 天历史基线，不保存或立即显示旧页面行；市值则独立保存在 `market_caps.json`。短时间重启会复用未过期的历史基线和最后一次成功市值，减少对外部接口的重复请求。可用 `--snapshot-save-interval` 调整 OI 缓存写入间隔，正常停止时还会保存一次最后完成的批次。损坏、嵌套过深或异常过大的缓存会被忽略，并在新数据到达后重建，不会阻断服务启动。

单个合约短暂更新失败时会保留最后一行，避免页面闪烁；连续 15 分钟没有成功更新时，该行会自动清理，恢复成功后重新出现。合约名称仍会保留在独立集合中，仅用于名单缩水检查。
每个合约的有效期从其当前 OI 响应到达时单独计算；同批其他合约的慢请求或历史 OI 重试不会延长这 15 分钟。
如果本地服务无法访问，或后台 OI 轮询线程意外停止，浏览器会在连续异常 15 分钟后清空旧行，而不是无限保留最后一次画面。
标签页不可见或所在窗口失去焦点时只暂停页面动画，价格 WebSocket 和 OI 请求会继续更新；重新显示或获得焦点后会立即补一次 OI 刷新。
电脑休眠或系统时间明显跳变后，服务端会清空易过期的行、市场行情和历史 OI 缓存，保留已知合约集合及最后一次成功市值并重新分批获取，避免把休眠前的 OI 数据继续当成实时数据。
API 返回数据前还会独立检查最近成功批次的墙上时钟时间；即使系统休眠期间单调时钟没有推进，超过 15 分钟的内存行也不会重新显示。

合约名单默认每 15 分钟刷新。刷新请求失败或返回的名单异常缩水时，服务会继续使用当前名单轮询，并在 60 秒后重试，不会立即删除大量现有数据；如果同一份大幅缩减名单连续两次返回，则把它视为已确认变更并接受，避免长期停机后的旧名单永久阻断启动。
合约确认下架后，服务端会从页面数据和缓存中移除它，浏览器也会根据完整活跃合约名单同步删除对应的本地收藏；服务刚启动或合约名单请求异常时不会清空收藏。

24 小时和 7 天变化按历史记录的真实时间戳匹配。价格(7d%)使用同一条 7 天 OI 历史记录中的持仓价值除以持仓数量得到历史价格，不会增加单独的 K 线请求；当前端 WebSocket 价格变化时会实时重算。历史基线缓存不会超过来源点剩余的两小时容差；到期后即使配置了更长缓存也会重新请求。历史接口短暂失败时，只会回退仍在容差内的基线；超出范围就显示 `-`，不会无限复用旧数据或用错误跨度代替。

主排行表使用固定行高的虚拟滚动，只创建当前视口附近的行；排序、筛选、收藏和实时价格更新仍作用于完整数据集。

上方 7D OI 异动信号可切换最低 7 天 OI 变化和最低持仓价值。两张表使用类似自动减仓指示器的五格灯显示 OI 新鲜度：20 秒内为 1 格绿色，超过 20 秒且不足 1 分钟为 3 格黄色，满 1 分钟后为 5 格红色；15 分钟未成功更新仍会按服务端规则移除。悬停合约行仍可查看具体相对更新时间。

悬停任意合约行会显示完整行情、OI 与更新时间详情。主排行的排序字段和升降序保存在当前浏览器中，刷新页面后继续沿用。

浏览器端价格流与页面渲染分离：Binance WebSocket 先在独立数据源中合并同一帧的 ticker，再发布批次更新；OI 定时请求和过期判断由独立刷新控制器管理；筛选、排序、高 OI 信号和热力范围由 Web Worker 计算，Worker 不可用时自动回退主线程。UI 使用独立调度器合并到单一 `requestAnimationFrame` 队列提交更新，两张表共用同一套行情单元格并复用已有行节点，不通过 `innerHTML` 重建。

## 测试与前端检查

运行后端单元测试：

```bash
python3 -m unittest discover -s tests -v
```

前端静态检查无需安装依赖，会验证 JavaScript 模块、HTML 元素引用及拆分后的 CSS 文件：

```bash
node realtime_oi_dashboard/scripts/check-static-js.mjs
```
