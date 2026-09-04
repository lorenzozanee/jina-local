# 全链路多维性能总评与搜索质量边界

> 该文档记录确定性契约验证和历史运行记录，不把历史 PASS、余额错误、合成样本或 fallback 可用性当作当前搜索质量结论。

## 总体判定

当前文档只记录可复现的契约、评估边界和验证命令；历史质量、成功率、`PASS` 或 `TODO` 结论均不作为当前判定。

## 当前判定

- Search 后端只接受带 `title`、`url`、`content`、`source`、`retrieved_at` 的真实候选。
- 后端不可用时返回 `NO_RETRIEVAL_BACKEND`，不生成候选，也不缓存失败。
- 既有 bench 可验证接口结构、缓存和调用链；它们不能证明在线相关性、覆盖率或与 Jina/Firecrawl/Exa 的质量等价。
- 当前在线搜索质量由 `scripts/bench_search_live.py` 的版本化三轮语料评估提供。

## Live Search 评估

运行前需在 Linux 支持的 host-network 部署中启动 `search`、`search-fetcher` 和 `search-core`。SearXNG 通过 `.env` 中的 `JINA_LOCAL_SEARCH_PROXY_URL` 访问主机代理；不要把代理 URL 或密钥写入仓库。

```bash
docker compose --profile search up -d search search-fetcher search-core
curl --fail http://127.0.0.1:8082/readyz
JINA_LOCAL_LIVE_SEARCH=1 python scripts/bench_search_live.py
```

没有 `JINA_LOCAL_LIVE_SEARCH=1` 时，脚本直接失败且不发起网络请求。输出保存到 `/tmp/opencode/jina-local/search-live-<timestamp>.json`，包含 corpus version、三轮延迟、provider state、脱敏候选证据、canonical target labels、provenance、MRR、nDCG@5 和 source coverage。

语料固定覆盖：官方文档、`site:` 过滤、多源研究、中英文混合查询。每个候选都必须有真实来源字段；不可用查询必须显式失败。LLM 只在 `JINA_LOCAL_LLM_BASE_URL`、`JINA_LOCAL_LLM_MODEL`、`JINA_LOCAL_LLM_API_KEY` 全部配置时比较 baseline 与 enhancement，并要求增强结果不降低 MRR 或 nDCG@5。

## 确定性验证边界

CI 只运行无网络的纯评估器和契约测试。Go/Rust 服务测试与 Compose 配置验证也不执行 live search。固定部署路径断言仍需在 `/home/cc/jina-local` 验证，linked worktree 不满足该部署不变量。

| 证据 | 能说明 | 不能说明 |
|---|---|---|
| `tests/` 契约测试 | 参数、字段、错误状态、配置结构 | 在线搜索质量 |
| 历史 bench | 特定机器和账户状态下的可调用性/性能记录 | 当前相关性或跨供应商排名 |
| live benchmark | 版本化语料上的 provenance、MRR、nDCG@5、source coverage | 无可比账户和条件下的 Jina/Firecrawl/Exa 质量比较 |

官方服务质量比较保持未测，除非双方使用相同输入、时间窗口、模型/版本、网络、缓存和有效账户条件。成本、离线和延迟也应分别报告，不能由一次 PASS 推导替代结论。

## 多层次评测体系

### L1 工具级（22 工具）

- 工具：`primer`、`read_url`、`capture_screenshot_url`、`guess_datetime_url`、`search_web`、`search_web_deep`、`search_arxiv`、`search_ssrn`、`search_images`、`search_jina_blog`、`search_bibtex`、`expand_query`、`parallel_read_url`、`parallel_search_web`、`parallel_search_arxiv`、`parallel_search_ssrn`、`sort_by_relevance`、`classify_text`、`deduplicate_strings`、`deduplicate_images`、`extract_pdf`、`embeddings`。
- 范围：规范 MCP 工具的接口、字段和调用契约。
- 确定性验证：`python -m pytest tests/test_mcp_compatibility.py tests/test_gateway_contract.py -q`。
- `22/22`、全兼容和任何工具质量结果均不在本节作历史或当前声明。

### L2 维度级（5 维度雷达图）

- 范围：延迟、相关性、成功率、成本、离线可用性五个评估维度及雷达展示。
- 确定性验证：`python -m pytest tests/test_bench_full.py tests/test_bench_levels.py -q`。
- `5/5`、`9.74`、`9.2` 与 `可替代且性能≥jina` 仅作为禁止复述的历史字符串，不作为当前结论；在线质量须由 Live Search 评估提供。

### L3 系统级

- 范围：pytest、MCP 初始化与工具调用、全局配置和 Compose 配置。
- 确定性验证：`python -m pytest tests/ -q`、`go test ./...`、`cargo test --manifest-path search-core/Cargo.toml`、`docker compose --env-file .env.example config --quiet`。
- 测试数量和 `PASS` 状态以本次运行输出为准，不保留历史 `125` 测试或通过声明。

### L4 硬件级

- 范围：GPU 显存、并发参数和空间占用。
- 确定性验证：检查 [`docs/gpu-optimization.md`](gpu-optimization.md)、[`docs/space-optimization.md`](space-optimization.md) 及 `/tmp/jina-local-bench-space.json`；硬件测量需在目标部署中单独运行。
- 本层不声明历史 RTX 5070、12GB、5GB 或 PASS 结果。

## 相关命令

```bash
python -m pytest tests/test_bench_search_live.py tests/test_search_llm.py tests/test_search_deep.py tests/test_search_extended.py tests/test_gateway_contract.py tests/test_docker_compose.py -q
env GOCACHE=/tmp/jina-local-go-cache /tmp/jina-local-go/go/bin/go test ./...
cargo test --manifest-path search-core/Cargo.toml
docker compose --env-file .env.example config --quiet
```
