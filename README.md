# jina-local

> 系统全局本地化替代 `jina.ai` 的 Reader / Search / Reranker / Embeddings 能力，供所有 OpenCode Agent 通过 MCP 统一调用。

## 定位

本项目部署在宿主机 **GPU (NVIDIA GeForce RTX 5070 12GB)** 上，目标是**完全本地化替代**线上 `jina.ai` 服务，摆脱对 `jina.ai` 云端 API 的依赖，实现离线可用、低延迟、可控成本的本地推理栈。

**系统全局路径固定为 `~/jina-local`（即 `/home/cc/jina-local`），而非任意 git worktree / 临时目录**。所有 OpenCode agent、MCP 配置、docker 部署均以该路径为准，确保全局唯一、可被所有会话复用。

> ⚠️ 约束：不要在 `asset-workflow` 等业务仓库的 worktree 下创建 `jina-local`，以免随 worktree 删除而丢失。

## 替代的 Jina 能力 / MCP Tools

| 原 jina.ai 能力 | 原 MCP Tool | 本地替代目标 |
|---|---|---|
| **Reader** - URL 转 Markdown / 抽取正文 | `jina_read_url` / `read_url` / `omnireach_omnireach_fetch` / `firecrawl_scrape` | 本地 Reader 服务：JS 渲染 + Readability 抽取 + Markdown 清洗 |
| **Search** - 联网搜索（片段） | `jina_search_web` / `search_web` | 本地 Search 聚合：SearXNG / 自建索引 + 搜索结果归一化 |
| **Search Deep** - 搜索并全文读取 | `jina_search_web_deep` / `search_web_deep` | Search + Reader 流水线：搜索后并行抓取正文、返回最相关段落 |
| **Reranker** - 相关性重排 | `jina_sort_by_relevance` / `sort_by_relevance` | 本地 Reranker 模型（`bge-reranker` / `jina-reranker` 本地版） |
| **Embeddings** - 向量嵌入 | `jina_embeddings` (隐式) | 本地 Embeddings 模型（`bge-m3` / `jina-embeddings-v3` 本地版） |
| **Deduplicate** - 去重 | `jina_deduplicate_strings` / `jina_deduplicate_images` / `deduplicate` | 本地基于 Embedding 余弦相似度的语义去重 |
| **Classify / Expand** | `jina_classify_text` / `jina_expand_query` | 本地 Zero-shot 分类 + Query 改写（可选） |
| **Images Search** | `jina_search_images` | 预留，后续接入本地或代理搜索 |

所有对外暴露的 MCP Tool 保持与 `jina.ai` 兼容的接口签名，`opencode` 侧仅需切换 MCP endpoint 即可无感迁移。

## 架构（规划）

```
~/jina-local/
├── docker-compose.yml      # GPU 推理服务编排（embeddings / reranker / reader / search）
├── .env.example            # 环境变量模板
├── mcp-gateway/            # MCP 网关：对上兼容 jina MCP Tools，对下路由到本地服务
│   ├── pyproject.toml
│   └── src/
└── tests/                  # 集成/契约测试（对齐 jina.ai 返回格式）
```

- **推理层**：Embeddings / Reranker 跑在 RTX 5070 12GB 上，显存预算内按需加载/量化。
- **网关层**：`mcp-gateway` 用 Python 实现 MCP Server，协议兼容现有 `jina` MCP，供 `opencode` 全局配置调用。
- **部署层**：`docker-compose.yml` 一键拉起，`/tmp/opencode` 作为临时缓存（遵循项目规范）。

## 目录结构

```
~/jina-local/
├── README.md
├── docker-compose.yml
├── .env.example
├── mcp-gateway/
│   ├── pyproject.toml
│   └── src/
└── tests/
```

> 当前为骨架阶段，仅占位，不包含具体业务代码。

## 快速开始（占位）

```bash
# 克隆后
cd ~/jina-local
cp .env.example .env
# 编辑 .env 填入本地模型路径、端口等
docker compose up -d
# 在 opencode 中将 jina MCP 指向本地 mcp-gateway
```

## 硬件要求

- GPU: NVIDIA GeForce RTX 5070 12GB（已验证 `nvidia-smi` 可用，CUDA 13.2）
- 显存策略：Embeddings 与 Reranker 错峰/量化加载，避免 OOM

## 关联规范

- 全局路径 `~/jina-local`，禁止放入 worktree
- MCP 调用统一走 `mcp-gateway`，保持与 `jina.ai` Tool 兼容
- 后续按「最小可用 -> 逐层加能力」演进，不做过渡性兼容层
