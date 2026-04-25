# nanobot 接入 yls 第三方中转说明

本文档记录 `nanobot` 接入 yls 第三方中转的排查过程、最终结论、已落地修改，以及后续维护方式。目的是让新的 Codex 会话可以快速理解当前状态，不必重复从头排查。

## 背景

- 用户希望把 yls 第三方中转接入 `nanobot`
- 已知信息保存在 [yls.txt](/Users/marin/config/llm/yls.txt)
- 第三方端点：
  - base URL: `https://code.ylsagi.com/codex`
  - model: `gpt-5.4`
- 同一组配置在 Codex CLI 中可以正常使用

## 核心结论

问题不是 `key` 被封，也不是 `nanobot` 不能接第三方本身，而是 **协议形状不匹配**。

- Codex CLI 的自定义 provider 配置为 `wire_api = "responses"`
- yls 端点支持的是 `Responses API`
- `nanobot v0.1.5.post2` 的 `custom` provider 默认走 `OpenAI-compatible chat/completions` 逻辑
- 对第三方域名，`nanobot` 不会自动切到 `/responses`
- 因此原始状态下 `nanobot` 会请求错误路径，导致接不上

## 实测结果

已确认以下结论：

- `GET https://code.ylsagi.com/codex/models` 返回 `404`
- `POST https://code.ylsagi.com/codex/chat/completions` 返回 `404`
- `POST https://code.ylsagi.com/codex/responses` 返回 `200`

因此 yls 当前应按 `Responses API` 方式接入。

## 当前有效方案

当前机器上已经落地以下方案：

1. 给 `nanobot` 增加 `providers.custom.wireApi` 配置项
2. 当 `wireApi = "responses"` 时，强制 `custom` provider 走 `Responses API`
3. `~/.nanobot/config.json` 中的 `providers.custom` 已切到 yls
4. `uv tool` 已改为从本地源码目录以 `editable` 模式安装

## 当前配置位置

### nanobot 运行配置

文件：[config.json](/Users/marin/.nanobot/config.json:225)

当前关键字段：

```json
"custom": {
  "apiKey": "见本地配置文件",
  "apiBase": "https://code.ylsagi.com/codex",
  "extraHeaders": null,
  "wireApi": "responses"
}
```

说明：

- 不要把 `wireApi` 改回默认行为，否则大概率会再次走错到 `chat/completions`
- `apiKey` 已写入本地配置，文档中不重复展开

### yls 原始记录

文件：[yls.txt](/Users/marin/config/llm/yls.txt)

## 本地源码仓库

本机已经拉取源码仓库：

- 路径：[nanobot](/Users/marin/code/nanobot)
- 对齐版本：`v0.1.5.post2`

当前 `uv` 安装来源已经切到本地源码，而不是纯 PyPI 包。

因此后续日常使用方式 **不变**：

```bash
nanobot agent
nanobot status
nanobot serve
```

## 已修改源码

以下文件已做本地修改：

- [nanobot/config/schema.py](/Users/marin/code/nanobot/nanobot/config/schema.py:101)
  - 为 `ProviderConfig` 增加 `wire_api: Literal["auto", "chat_completions", "responses"]`
- [nanobot/providers/openai_compat_provider.py](/Users/marin/code/nanobot/nanobot/providers/openai_compat_provider.py:178)
  - 支持显式指定 `wire_api`
  - 当 `wire_api == "responses"` 时强制走 Responses API
  - 当显式指定 `responses` 时，不再自动回退到 `chat/completions`
- [nanobot/cli/commands.py](/Users/marin/code/nanobot/nanobot/cli/commands.py:463)
  - 创建 provider 时传入 `wire_api`
- [nanobot/nanobot.py](/Users/marin/code/nanobot/nanobot/nanobot.py:166)
  - 创建 provider 时传入 `wire_api`

## 验证结果

已通过以下验证：

```bash
nanobot --version
nanobot agent -m "只回复 pong" --no-markdown
```

实际返回：

- 版本正常：`v0.1.5.post2`
- agent 请求正常返回：`pong`

## 后续维护建议

推荐按下面方式维护，不要再直接手改 `site-packages`：

1. 在 [nanobot](/Users/marin/code/nanobot) 中维护补丁
2. 继续使用 `uv tool` 的本地 editable 安装
3. 升级时先更新源码仓库，再检查补丁是否仍需要保留

## 如果后续升级 nanobot

建议流程：

1. 进入本地源码目录 `"/Users/marin/code/nanobot"`
2. 拉取上游最新代码
3. 检查以下 4 个文件是否仍需要保留本地补丁
4. 重新验证 `nanobot agent -m "只回复 pong" --no-markdown`

重点检查：

- `nanobot/config/schema.py`
- `nanobot/providers/openai_compat_provider.py`
- `nanobot/cli/commands.py`
- `nanobot/nanobot.py`

如果上游未来原生支持 `custom.wireApi` 或第三方 `Responses API` 配置，则可以考虑删掉本地补丁，改回上游标准实现。

## 给未来 Codex 会话的提示

如果新会话要继续处理这个问题，请先阅读以下内容：

1. 本文档：[yls-responses-integration.md](/Users/marin/code/nanobot/docs/yls-responses-integration.md:1)
2. 当前 nanobot 配置：[config.json](/Users/marin/.nanobot/config.json:225)
3. 本地源码改动：[nanobot](/Users/marin/code/nanobot)
4. yls 原始记录：[yls.txt](/Users/marin/config/llm/yls.txt)

需要优先记住的事实：

- yls 端点当前可用
- 它支持 `POST /codex/responses`
- 它不符合 `nanobot v0.1.5.post2` 默认 `custom` provider 的自动路由假设
- 当前修复依赖 `wireApi = "responses"`
- 当前 `nanobot` 是从本地源码 editable 安装的

## 非目标

这次处理没有做以下事情：

- 没有创建 git 分支
- 没有提交 commit
- 没有向上游提交 PR

如果后续要做工程化收口，可以继续补：

- 创建本地分支
- 提交补丁
- 视情况向上游提 PR
