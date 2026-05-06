# 投资助手使用指南

投资助手用于监控固定的 A 股与场内 ETF 自选池，通过 AkShare 读取已收盘行情周期，结合你手动维护的持仓状态，在聊天渠道中发送可执行提醒。

它是规则驱动的提醒系统，不会自动下单，不保证收益，不做全市场扫描，也不做基本面、新闻或情绪分析。

## 前置条件

- Python 3.11+。
- 安装投资依赖，让运行环境具备 AkShare：

```bash
pip install -e ".[investment]"
```

使用 `uv` 时可以这样启动：

```bash
uv run --python 3.12 --extra investment nanobot gateway
```

- 至少配置一个外部聊天渠道。一期推荐使用微信/Weixin。
- 启动 gateway，使后台扫描和聊天命令生效：

```bash
nanobot gateway
```

## AkShare 是否需要单独部署

不需要。AkShare 是 Python 数据接口库，不是你需要自己部署的行情服务。安装 `investment` extra 后，nanobot 会在运行时通过 AkShare 调用公开数据源接口。

投资助手当前会使用 AkShare 获取：

- A 股分钟 K 线
- 场内 ETF 分钟 K 线
- 中国市场交易日历

## 使用 JQData 作为主行情源

如果你希望使用聚宽 JQData 作为主行情源，并在 JQData 查询失败时回退到 AkShare，可以安装额外依赖：

```bash
pip install -e ".[investment,investment-jqdata]"
```

配置示例：

```json
{
  "investment": {
    "marketDataProvider": "jqdata",
    "fallbackProvider": "akshare",
    "jqdataUsername": "你的聚宽账号",
    "jqdataPassword": "${JQDATA_PASSWORD}"
  }
}
```

JQData 使用聚宽证券代码格式。nanobot 会把常见 A 股/ETF 六位代码自动转换为 `600519.XSHG`、`159992.XSHE` 这类格式。

## AkShare 是否需要代理

通常不需要。是否需要代理取决于运行机器能否稳定访问 AkShare 调用的上游公开数据源。

建议按下面顺序判断：

1. 先不配置代理，直接运行一次 `/invest status <symbol>`。
2. 如果能返回动态状态，说明当前网络可用，不需要代理。
3. 如果频繁出现连接超时、上游不可用、网络重置等错误，再考虑为运行环境配置代理。

如果你的服务器在公司内网、境外机房或网络出口受限环境中，可能需要代理。AkShare 本身没有要求 nanobot 内部配置代理；一般通过系统环境变量让 Python HTTP 请求走代理：

```bash
export HTTP_PROXY="http://127.0.0.1:7890"
export HTTPS_PROXY="http://127.0.0.1:7890"
```

Windows PowerShell 示例：

```powershell
$env:HTTP_PROXY="http://127.0.0.1:7890"
$env:HTTPS_PROXY="http://127.0.0.1:7890"
```

然后在同一个终端里启动：

```bash
nanobot gateway
```

如果你使用 systemd、Docker 或进程管理器，需要把代理环境变量配置到对应服务环境中，而不是只在当前交互终端里设置。

## 监控范围

投资助手只评估你添加到自选池或持仓中的标的。

支持的资产类型：

- `stock`：A 股个股
- `etf`：场内 ETF

所有正式决策只基于已收盘完整周期 K 线，不使用未收盘的盘中 K 线抢跑。

## 交易时间与交易日历

后台扫描只会在中国市场交易日历确认开市，并且当前时间位于以下交易时段时运行：

- `09:30-11:30`
- `13:00-15:00`

系统会通过 AkShare 的中国交易日历跳过周末和法定休市日，并支持调休形成的实际交易日。

如果交易日历不可用，或无法确认当天是否开市，系统会保守跳过本轮扫描，不发送常规播报。

## 状态文件位置

投资状态保存在当前 nanobot workspace 中：

```text
<workspace>/investment/state.json
```

状态内容包括：

- 自选池
- 持仓
- 风险模式
- 扫描周期

## 聊天命令

以下命令可以在已连接的聊天渠道或交互会话中发送。

### 查看帮助

```text
/invest
```

显示全部投资助手命令。

### 添加自选标的

```text
/invest watch add <symbol> <stock|etf>
```

示例：

```text
/invest watch add 600519 stock
/invest watch add 510300 etf
```

### 删除自选标的

```text
/invest watch remove <symbol>
```

示例：

```text
/invest watch remove 510300
```

### 新增或更新持仓

```text
/invest position set <symbol> <stock|etf> <cost_basis> <tranche_state> <latest_buy_date> <shares>
```

`tranche_state` 必须是以下值之一：

- `flat`：无有效持仓
- `entry`：首仓
- `add1`：第一次加仓后
- `full`：已达到计划满仓档

`latest_buy_date` 必须使用 `YYYY-MM-DD` 格式。

示例：

```text
/invest position set 510300 etf 3.85 entry 2026-04-29 1000
/invest position set 600519 stock 1680.5 add1 2026-04-28 100
```

系统会使用 `latest_buy_date` 判断 T+1 约束。如果当天买入后出现减仓或卖出信号，系统会展示逻辑，但标记为当前不可执行。

### 清除持仓

```text
/invest position clear <symbol>
```

示例：

```text
/invest position clear 600519
```

该命令只删除持仓记录，不会从自选池中删除标的。

### 设置风险模式

```text
/invest mode <conservative|balanced|aggressive>
```

示例：

```text
/invest mode conservative
/invest mode balanced
/invest mode aggressive
```

风险模式会影响技术信号的阈值严格程度。

### 设置扫描周期

```text
/invest interval <minutes>
```

示例：

```text
/invest interval 60
```

扫描周期控制行情 K 线周期。常用值包括 `30`、`60`、`90`、`120`。

### 查看静态配置

```text
/invest show
```

展示已保存的自选池、持仓、风险模式和扫描周期。该命令不会拉取最新行情。

### 查询单个标的动态状态

```text
/invest status <symbol>
```

示例：

```text
/invest status 510300
```

标的必须已经存在于自选池或持仓中。该命令会拉取最新已收盘周期行情，并返回：

- 最新已收盘周期时间
- 资产类型
- 当前持仓状态
- 建议动作
- 触发原因
- 失效条件
- 风险提示
- 当前是否可执行

### 查询全部持仓动态状态

```text
/invest status positions
```

该命令会对当前所有持仓标的拉取最新已收盘周期行情，并返回持仓动态摘要。如果部分标的临时查询失败，系统会展示成功结果并列出失败标的。

## 后台播报

当 `nanobot gateway` 正在运行时，投资助手会在确认开市的交易时段内按配置周期扫描自选池。

每次状态播报包含：

- 自选池数量
- 持仓数量
- 本轮新增或变化的正式信号数量
- 新增或变化的正式信号详情

正式信号包括：

- `买入`
- `加仓`
- `减仓`
- `卖出`

如果已收盘周期和正式信号快照没有变化，系统会抑制重复的正式信号详情，避免重复提醒。

## 推荐首次运行流程

1. 安装投资依赖：

```bash
pip install -e ".[investment]"
```

2. 启动 gateway：

```bash
nanobot gateway
```

3. 添加少量自选标的：

```text
/invest watch add 510300 etf
/invest watch add 600519 stock
```

4. 如有持仓，录入当前持仓：

```text
/invest position set 510300 etf 3.85 entry 2026-04-29 1000
```

5. 设置风险模式和扫描周期：

```text
/invest mode balanced
/invest interval 60
```

6. 查看静态配置：

```text
/invest show
```

7. 查询一次动态状态：

```text
/invest status 510300
```

8. 在交易时段内观察 gateway 日志和聊天播报 1-2 个扫描周期，确认消息、交易日历和行情数据都正常后，再长期运行。

## 常见问题

### 提示 Investment market data dependency is missing

说明当前环境没有安装投资依赖。执行：

```bash
pip install -e ".[investment]"
```

### 没有收到后台播报

按顺序检查：

- `nanobot gateway` 是否正在运行。
- 是否已启用至少一个外部聊天渠道。
- 是否已经和 bot 在该渠道中互动过，确保存在可投递会话。
- 自选池是否为空。
- 当前时间是否在 `09:30-11:30` 或 `13:00-15:00`。
- 当前日期是否为中国市场开市日。
- AkShare 数据源是否可访问。

### `/invest status <symbol>` 提示标的不存在

先添加到自选池，或录入为持仓：

```text
/invest watch add <symbol> <stock|etf>
```

### 状态文件不可读

修复或删除：

```text
<workspace>/investment/state.json
```

系统不会自动覆盖不可读的状态文件。

## 安全说明

- 投资助手只提供规则驱动提醒，不会自动下单。
- T+1 可执行性只是系统根据保存的最近买入日期做出的提示，最终仍需以券商实际规则为准。
- 行情数据可能延迟、缺失或临时不可用。
- 所有提醒都应作为复核提示，不构成投资建议。
