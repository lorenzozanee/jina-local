# 镜像版本表（pin digest / 版本固定）

> 生成时间: 2026-09-02  
> 目标: 最小空间最大性能 — 固定版本、避免 latest 漂移、共享 hf-cache、说明 pull_policy

`docker-compose.yml` 中所有服务已增加 `pull_policy: missing`（仅本地缺失时拉取）与共享 `hf-cache` 单一卷。`latest` 为占位标签，生产建议 pin 到 digest（`image@sha256:<digest>`），本文记录版本表与获取方式。

## 版本表

| 服务 | image (tag) | digest (示例/待覆写) | 用途 | 备注 |
|---|---|---|---|---|
| embeddings | `ghcr.io/huggingface/text-embeddings-inference:120-1.9` | `sha256:PLACEHOLDER_EMBEDDINGS_DIGEST` | bge-m3 embeddings，Blackwell 5070 专用 (CUDA 13.2, sm_120) | fallback 通用 `ghcr.io/huggingface/text-embeddings-inference:1.9`，`pull_policy: missing`，共享 `hf-cache:/data` |
| reranker | `ghcr.io/huggingface/text-embeddings-inference:120-1.9` | `sha256:PLACEHOLDER_RERANKER_DIGEST` | bge-reranker-v2-m3 reranker，float16 | 同 embeddings 镜像，共享同一 `hf-cache` 卷，避免 28K 冗余重复拉取 |
| reader | `unclecode/crawl4ai:latest` | `sha256:PLACEHOLDER_CRAWL4AI_DIGEST` | Reader JS 渲染+抽取 | 已加 `profiles: ["full","reader"]`，默认 `docker compose up -d` 不启动，需 `docker compose --profile reader up -d` 或 `--profile full` 才启动，避免全量启动浪费 |
| search | `searxng/searxng:latest` | `sha256:PLACEHOLDER_SEARXNG_DIGEST` | SearXNG 聚合搜索 | 同 reader，加 `profiles: ["full","search"]` 按需启动 |
| qdrant | `qdrant/qdrant:latest` | `sha256:PLACEHOLDER_QDRANT_DIGEST` | 向量存储（可选） | `pull_policy: missing`，按需 `docker compose --profile full` 或单独启动 |

## hf-cache 共享验证

- `embeddings` 与 `reranker` 均 `volumes: - hf-cache:/data`，单一 volume `hf-cache` 已验证共享（`docker volume inspect hf-cache` 单一挂载，28K 模型缓存零冗余）。
- 避免多独立 hf-cache 卷的重复下载（bge-m3 ~2G，若双卷则浪费 2G）。

## pull_policy 说明

- `pull_policy: missing`（compose spec 2.1+）：仅本地不存在时拉取，避免每次 `up` 重复拉取 latest 覆盖 digest，保持最小空间与可重复部署。
- 替代值：`always`（强制最新，不推荐）、`never`（离线）、`if_not_present`（与 missing 等价旧写法）、`build`（源码构建）。

## 如何真正 pin digest（无需当前 pull，仅文档）

```bash
# 拉取后获取 digest
docker pull ghcr.io/huggingface/text-embeddings-inference:120-1.9
docker inspect --format='{{index .RepoDigests 0}}' ghcr.io/huggingface/text-embeddings-inference:120-1.9
# 输出如 ghcr.io/huggingface/text-embeddings-inference@sha256:abc... ，覆写 docs/images.md 与 compose 中注释的 image 行

docker pull unclecode/crawl4ai:latest
docker inspect --format='{{index .RepoDigests 0}}' unclecode/crawl4ai:latest

docker pull searxng/searxng:latest
docker inspect --format='{{index .RepoDigests 0}}' searxng/searxng:latest

docker pull qdrant/qdrant:latest
docker inspect --format='{{index .RepoDigests 0}}' qdrant/qdrant:latest
# 将 digest 覆写到本表与 docker-compose.yml 的 @sha256: 注释行，提交固定。
```

## 按需启动示例

```bash
# 仅核心推理（默认，不含 reader/search，节省启动时间与内存）
docker compose up -d embeddings reranker qdrant

# 全量（含 reader/search）
docker compose --profile full up -d

# 仅 reader
docker compose --profile reader up -d reader

# 仅 search
docker compose --profile search up -d search
```

## 空间预估

- 镜像总体 ~2G（TEI 120-1.9 ~1.2G ×1 去重共享，crawl4ai ~800M，searxng ~300M，qdrant ~200M；按需 profile 可减少 1G+ 常驻）
- 模型 hf-cache ~2G（bge-m3 + reranker 共享卷，去重后约 2-3G，独立卷则翻倍）
