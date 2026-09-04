# 全链路多维性能总评与搜索质量边界

> 该文档记录确定性契约验证和历史运行记录，不把历史 PASS、余额错误、合成样本或 fallback 可用性当作当前搜索质量结论。

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

## 相关命令

```bash
python -m pytest tests/test_bench_search_live.py tests/test_search_llm.py tests/test_search_deep.py tests/test_search_extended.py tests/test_gateway_contract.py tests/test_docker_compose.py -q
env GOCACHE=/tmp/jina-local-go-cache /tmp/jina-local-go/go/bin/go test ./...
cargo test --manifest-path search-core/Cargo.toml
docker compose --env-file .env.example config --quiet
```
