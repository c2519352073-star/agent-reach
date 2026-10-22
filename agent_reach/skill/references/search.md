# 搜索工具

Exa 是面向 AI Agent 的语义搜索服务，不是传统关键词搜索引擎。

## Exa AI 搜索

高质量 AI 搜索引擎，适合查找技术文档、官方示例和相关网页。

```bash
mcporter call exa.web_search_exa query="query" numResults=5
mcporter call exa.web_search_exa query="library API code example" numResults=5
```

如果 `mcporter list` 显示 Exa `offline`，但端点
`https://mcp.exa.ai/mcp` 可访问，先重启 mcporter 守护进程：

```bash
mcporter daemon restart
mcporter list exa --json
```

`agent-reach doctor --deep --json` 会实际执行 `mcporter list exa --json` 并验证
Exa MCP 连接；普通 `doctor` 只检查配置，不启动远端服务。

不要把 Exa Authorization 写入仓库内的 `config/mcporter.json`。如果本地
`config/mcporter.json` 声明了 `exa`，它会覆盖 `~/.mcporter/mcporter.json`；
优先删除这个本地覆盖项，让带凭据的用户级配置生效。

### 使用场景

| 场景 | 参数 |
|-----|------|
| 网页搜索 | `web_search_exa(query: "...", numResults: 5)` |
| 技术/代码资料 | `web_search_exa(query: "框架名 API 示例", numResults: 5)` |

> Exa MCP 的 `get_code_context_exa` 已弃用且默认不注册。代码问题也使用
> `web_search_exa`；需要精确搜索仓库内容时，改用 `dev.md` 中的 GitHub 搜索。

### 特点

- 擅长英文内容和技术文档
- 可通过查询词定位官方文档和代码示例
- 结果质量高

## 与其他搜索工具对比

| 工具 | 来源 | 适用场景 |
|-----|------|---------|
| Exa | agent-reach | 英文/技术/代码搜索 |
| 智谱搜索 | my-mcp-tools | 中文搜索 |
| GitHub 搜索 | agent-reach (dev.md) | 仓库/代码搜索 |
