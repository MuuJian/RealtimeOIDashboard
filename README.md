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
http://127.0.0.1:8777
```

按 `Control + C` 可以停止程序。

### 用手机访问本地面板

手机和电脑连接同一个网络，然后这样启动：

```bash
.venv/bin/python main.py --host 0.0.0.0 --port 8777
http://192.168.xxx.xxx:8777
```

其中 `192.168.xxx.xxx` 需要替换成电脑当前的局域网 IP。

## 可选设置

正常使用不需要修改。网络不稳定或请求过快时，可以降低更新速度：

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
