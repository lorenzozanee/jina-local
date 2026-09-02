# 官方 Jina AI 服务/API vs jina-local：多尺度、控制变量对比

> 文档性质：基于当前仓库源码、README、AGENTS、docs、tests 与 bench 脚本的工程对比。本文不是官方产品测评，也不把接口同名当成实现等价。
>
> 结论等级：**代码事实**表示可以从当前仓库直接核对；**已有 benchmark 声称**表示沿用仓库已有报告的结果，但不替代独立质量评测；**需实测/不可公平比较**表示当前证据不足，或两侧运行边界不同。

## 先说结论与边界

比较对象必须分开理解：官方一侧是 Jina AI 托管的 Search Foundation API，包括 Reader `r.jina.ai`、Search `s.jina.ai`、Embeddings `api.jina.ai/v1/embeddings`、Reranker `api.jina.ai/v1/rerank`，以及官方模型和 ReaderLM；本地一侧是本仓库的 Python MCP gateway，后面接本地抽取器、搜索聚合器、可选模型和缓存。官方 Reader、Embeddings、Reranker、模型产品的定位以官方页面为准：[Reader](https://jina.ai/reader/)、[Embeddings](https://jina.ai/embeddings/)、[Reranker](https://jina.ai/reranker/)、[Models](https://jina.ai/models/)。端点入口分别见 [Reader endpoint](https://r.jina.ai/)、[Search endpoint](https://s.jina.ai/)、[Embeddings endpoint](https://api.jina.ai/v1/embeddings)、[Reranker endpoint](https://api.jina.ai/v1/rerank)。

在工程取舍上，jina-local 适合内网、隐私、断网、可控成本、可自定义部署，以及希望继续使用 Jina 风格工具签名的 Agent 工作流。官方服务适合需要托管抓取与搜索覆盖、官方模型能力、集中运维、弹性和供应商服务边界的场景。两者可以做“替代路径”比较，不能宣称“官方服务的本地同等实现”，更不能由接口兼容、单次 PASS 或余额不足时的成功率推导质量等价。

特别是官方线上 Search/Reader 在互联网和供应商基础设施上运行，本地后端在用户的 CPU/GPU、网络、容器和缓存上运行；没有共同硬件、共同网络路径、共同索引快照和共同模型版本，因此不可能在同一硬件上严格闭环。成本也不是单一延迟指标：官方是服务用量与账户计费，本地是硬件、电力、运维和模型下载成本。本文不编造价格；README 和旧 bench 中的价格字符串只能视为历史记录，正式采购必须以官方当前页面和账户条款为准。

## 方法学与证据分级

本比较采用三层证据：

| 证据 | 可回答什么 | 不能回答什么 |
|---|---|---|
| 代码事实 | 暴露的工具、参数、调用链、后端、缓存、超时、容器资源 | 官方服务当前线上模型、索引质量、SLA、价格 |
| 已有 benchmark 声称 | 当前仓库曾在特定机器、样本和账户状态下测到的数字 | 公平的官方质量排名、泛化到生产流量 |
| 需实测/不可公平比较 | 需要同一数据、版本、时间窗口、网络条件后得到的结论 | 在条件不齐时给出确定结论 |

仓库自己的报告使用 `scripts/bench_full.py` 汇总 7 份 bench，报告称 21 工具、5 维度 PASS，本地 9.74/10、官方侧 3.6/10，成功率本地 134/134 对 20/127，见 `docs/bench-full.md:3-16`。但该报告同时记录 Search、Deep、Reranker、Embeddings 多数远端请求因 402 不可用（`docs/bench-full.md:20-28`），其分数把“服务暂时不可调用”当成质量和成功率差异。这个结果可以回答“该账户/该时段本地更可用”，不能回答“本地相关性超过官方”。

Reader bench 的 5 个 URL、每个 5 次运行、冷/热缓存和 p50/p95 逻辑见 `scripts/bench_reader.py:21-35`、`:132-188`；它测了 Markdown 字符数、标题、列表、代码和表格等结构代理指标（`:37-57`），不是人工或标注数据集上的语义质量。Search bench 的相关性是标题/正文关键词命中和 top1 命中（`scripts/bench_search.py:50-75`），也不是 Recall@k、MRR 或 nDCG。Embeddings bench 只有 6 组三元组（`scripts/bench_embeddings.py:32-43`），主要比较正负相似度差；Reranker bench 是 4 组人工构造文档并计算 nDCG（`scripts/bench_reranker.py:33-83`、`:99-120`）。

因此，stub/hash/词法代理、固定分数、少量人工样本和多数 PASS 都不能证明与官方服务等价。`tests/` 的主要价值是契约、输入校验、fallback、缓存、部署和可调用性；例如 `tests/test_mcp_compatibility.py:11-59` 定义了 21 个工具及必填参数，不能当作搜索质量测试。

## 控制变量表：先把比较做对

| 变量 | 控制要求 | 必须记录 |
|---|---|---|
| 输入 | 完全相同的 URL、查询、文档集、语言、字符编码；URL 记录抓取时间和 HTTP 状态 | 原始输入 SHA-256、响应快照、重定向链 |
| 模型 | Embeddings、Reranker 使用同一模型版本和精度；Reader 若比较模型抽取，固定 ReaderLM 版本与 prompt | model id、revision、dtype、最大长度；不能拿官方模型对本地 hash fallback |
| 输出规模 | 相同 `top-k`、`top-n`、chunk size、最大输入长度和字段规范 | 请求 payload、返回条数、截断规则 |
| 缓存 | 冷缓存：清理双方可控缓存后首请求；热缓存：预热后单独统计；不混合平均 | cache hit/miss、缓存位置、缓存 key、TTL |
| 并发与超时 | 预先固定并发阶梯（1/8/32/64/128）和端到端 timeout；官方限流与本地队列分别记录 | QPS、排队时间、超时、429/402/5xx、重试次数 |
| 网络 | 官方走固定出口和代理；本地分别测联网搜索、内网 SearXNG、完全断网 | RTT、出口、代理、DNS、服务可达性 |
| 硬件 | 本地记录 CPU、RAM、GPU 型号/显存、驱动、容器版本；官方硬件不可见 | `nvidia-smi`、RAM 峰值、CPU 时间、容器镜像 digest |
| 数据集 | Reader 用同一批静态页面；Search 用同一查询集和标注的相关文档；向量用公开检索集合 | 版本、语言分层、难例、去重规则、标注协议 |
| 统计 | 延迟报告 p50/p95（必要时 p99）；质量报告 Recall@k、MRR、nDCG@k、Exact/结构保真 | 样本量、置信区间、失败是否计入分母 |
| 资源与成本 | 每请求 token、输入输出 token、GPU 显存、CPU、RAM、磁盘、下载量分别计 | 官方账单字段；本地摊销硬件/电力/维护假设 |

官方 Search 页面当前存在“需要 key”的服务表述与示例端点形式之间的语境差异；本仓库脚本也对 `s.jina.ai` 使用 Bearer key（`scripts/bench_search.py:123-143`）。所以复测时应把匿名请求、带 key 请求、余额状态、HTTP 错误分开列，不把匿名 403、鉴权 401、余额 402 和真正的空结果统称为“搜索质量为零”。

## 能力矩阵

| 能力 | 官方托管对象 | jina-local 当前实现 | 证据与判定 |
|---|---|---|---|
| URL Reader | `r.jina.ai`，官方 Reader/ReaderLM 产品边界 | `requests` 抓取，trafilatura + readability + BeautifulSoup，清噪、Markdown、question 切片、缓存 | 代码事实：`reader.py:60-82`、`:234-240`；官方抽取质量需实测 |
| Web Search | `s.jina.ai` Search Foundation API | SearXNG 优先，DuckDuckGo/Bing/Brave 回退，归一化 URL、去重、词法排序、缓存 | 代码事实：`search.py:1`、`:147-187`、`:108-144`；索引覆盖和新鲜度不可直接等同 |
| Deep Search | 官方 Search/Reader 组合能力 | Search -> 并发 Reader -> chunk -> Reranker，另有内存和文件缓存 | 代码事实：`search_deep.py:1-3`、`:121-142`、`:174-229`；官方编排细节需实测 |
| Embeddings | `api.jina.ai/v1/embeddings` 与官方 embeddings 模型 | 默认 `BAAI/bge-m3`；TEI/`sentence-transformers` 优先，无模型时 hash TF + L2 fallback | 代码事实：`embeddings.py:1-5`、`:26-42`；模型空间不同，不可用维度一致推导语义一致 |
| Reranker | `api.jina.ai/v1/rerank` 与官方 reranker | CrossEncoder 可用时使用本地模型，否则 embeddings 余弦；批量、缓存、分片 | 代码事实：`reranker.py:1-7`、`:29-41`；本地模型 ID 与官方请求模型未必相同 |
| Academic/Image/工具 | 官方页面列出的能力与相关生态 | arXiv API、Semantic Scholar、Crossref/DBLP、DDG/SearXNG image、截图或 1x1 stub | 代码事实：`search_academic.py:1-9`、`:73-143`；“有函数”不等于官方端点语义相同 |

## 协议、API 与迁移性

`server.py` 创建 FastMCP 服务并支持 stdio、SSE、HTTP/streamable-http（`mcp-gateway/src/server.py:109-119`、`:310-334`）；工具包装器将 `read_url`、`search_web`、`sort_by_relevance` 等映射到 gateway，且同时注册原始函数名（`:121-148`、`:210-220`）。`gateway.py` 集中委托 Reader、Search、Embeddings、Reranker、Deep、Utils 和 Academic 模块（`gateway.py:9-146`），并保留 Jina 风格参数及 `top_k`/`limit` 等别名（`:149-212`）。这构成协议层面的迁移便利：Agent 可能无需更换工具名。

但协议兼容不覆盖 HTTP 头、鉴权、错误码、模型能力、响应字段的全部约束，也不覆盖官方服务的限流、索引和托管运维。官方端点是网络 API；本地入口默认是 MCP stdio，不是把本地 Python 函数伪装成官方 HTTP 服务。若上游严格依赖 OpenAI 风格 JSON、官方错误码或官方字段，应逐项做契约测试，不能只通过 `tests/test_mcp_compatibility.py`。

## 数据处理与质量

本地 Reader 删除 script/style/noscript/iframe/nav/footer，并将标题、列表、代码、表格转换为 Markdown（`reader.py:72-82`、`:123-193`）；它通过两个抽取器选择结果，并按问题对 chunk 做词重叠筛选。该路径透明、可审计、可定制，但遇到 JS 渲染、反爬、登录页、复杂 PDF 或特殊网页时，结果依赖本地抓取环境。官方 Reader 的价值在于其托管抓取、解析和官方模型产品边界；具体网页覆盖和保真必须用同一快照集测试。

本地 Search 的结果来自外部搜索源而不是 Jina 官方索引；它用词集合重叠、标题加权和短语 bonus 排序（`search.py:108-144`）。Deep Search 的词法 chunk 分数和本地 reranker 进一步决定最佳段落（`search_deep.py:133-142`、`:205-229`）。这意味着“搜索成功”只证明返回了结构正确的结果，不证明在目标任务上相关。应由独立标注集计算 Recall@k、MRR、nDCG@k，并按语言、主题、域名、长尾查询分层。

本地 embeddings 的真实模型后端应报告 `BAAI/bge-m3` 的版本；无模型或无依赖时则可能进入 384 维哈希向量（`embeddings.py:26-36`，说明及 fallback 在 `:1-5`）。本地 reranker 默认配置是 `cross-encoder/ms-marco-MiniLM-L6-v2`，不可用时退到向量余弦（`reranker.py:1-7`、`:29-41`）。因此必须在报告中记录 backend；hash/cosine 结果只能证明系统有降级可用性，不能和官方模型输出直接做质量排名。

## 性能、资源、成本与部署

性能方面，当前 Reader 报告称本地冷启动约 1.1-1.6 秒、官方约 0.9-1.2 秒，热缓存接近 0 秒，见 `docs/bench-reader.md:117-136`。这是特定 5 URL、5 次运行和当时网络/账户状态的结果，不是 SLA。Search/Deep/Embeddings/Reranker 的“官方不可用”结果见 `docs/bench-full.md:117-125`，不能拿本地缓存命中延迟与官方线上冷请求做同类比较。

资源方面，Compose 为 Embeddings 和 Reranker 使用 TEI、float16、`max-batch-tokens 16384`、`max-concurrent-requests 64`，共享 `hf-cache`；Reader 使用 CPU 型 crawl4ai，Search 使用 SearXNG，另有 Qdrant（`docker-compose.yml:1-40`、`:62-116`）。仓库文档以 RTX 5070 12GB 为例，估算双模型常驻约 5GB，并支持懒加载和闲置释放（`docs/gpu-optimization.md:10-18`、`:63-76`）。报告中的“>100 QPS”属于配置/bench 声称，应在目标硬件以 p95、错误率和显存峰值复测，不能视作官方吞吐承诺。

部署方面，官方将模型、抓取、搜索基础设施和扩缩容交给供应商，代价是网络、鉴权、账户和供应商变更依赖；本地需要 Docker Compose、Python 依赖、模型缓存、GPU 驱动（可 CPU 回退）和服务监控。`docker-compose.yml:118-120` 的 named volumes、`/tmp/opencode` 挂载和 `profiles` 让部署可拆分，但也引入镜像、模型和磁盘生命周期管理。成本比较应报告：官方实际账单与 token/请求统计；本地设备折旧、电力、模型下载、存储、维护人员时间。当前材料不足以给出任一方的普适美元价格。

安全与隐私方面，本地在完全断网、数据不离开主机的配置下有明显边界优势，但默认 Search/Reader 仍可能请求外部网站，Compose 示例还配置了代理（`docker-compose.yml:13-18`、`:43-47`）。需要 egress allowlist、日志脱敏、缓存目录权限、密钥不入仓库和容器最小权限。官方服务则需要评估 URL/文本是否发往供应商、数据保留政策、组织级密钥、区域合规和审计能力；本次仓库证据不能替官方作隐私承诺。

生态与可维护性方面，官方拥有集中更新的模型/服务生态和供应商维护；本地拥有源码可审计、可 pin 镜像/模型、可替换后端和 MCP 统一入口。维护负担也随之转移到本地：上游搜索源变化、网页解析回归、模型下载、GPU/CUDA、Compose 镜像和缓存清理都需要持续测试。`tests/` 覆盖 MCP、Reader、Search、Reranker、Embeddings、Utils 和 Compose 契约；`tests/test_bench_levels.py`、`tests/test_bench_full.py` 支持 L1-L4 的流程校验，但不等于在线质量回归。

## 建议的 L1-L4 验证与最小复测

1. **L1 工具级**：校验每个输入/输出契约、错误码映射、字段、top-k/top-n 和 MCP 注册；运行 `python -m pytest tests/test_mcp_compatibility.py tests/test_gateway_contract.py -v`。这是接口回归，不是官方质量证明。
2. **L2 维度级**：在同一 URL/查询/文档集上分别测冷、热缓存，输出 p50/p95、成功率、Recall@k、MRR、nDCG@k、Markdown 结构保真、token/请求。官方请求必须区分 key、匿名、402/401/403/429/5xx。
3. **L3 系统级**：固定依赖和配置，测端到端 MCP 调用、并发、超时、重试、日志、断网和恢复；运行 `python -m pytest tests/ -q`，再核对失败样本而非只看 PASS。
4. **L4 硬件级**：在目标机器记录 `nvidia-smi`、CPU/RAM 峰值、容器资源、磁盘和模型加载时间，分 GPU 模型、CPU 模型、hash/cosine fallback 三种 backend 测；执行 `python scripts/bench_embeddings.py`、`python scripts/bench_reranker.py` 和 `python scripts/bench_full.py`。官方硬件不可见，故 L4 只能分别报告，不能做同硬件比值。

最小可执行本地复测命令：

```bash
python -m pytest tests/ -q
python scripts/bench_reader.py
python scripts/bench_search.py
python scripts/bench_search_deep.py
python scripts/bench_embeddings.py
python scripts/bench_reranker.py
python scripts/bench_utils.py
python scripts/bench_mcp_global.py
python scripts/bench_full.py
```

复测后应把 `/tmp/jina-local-bench-*.json` 中的输入、backend、错误和缓存状态归档；不要只复制 `docs/bench-full.md` 的 PASS。对官方侧，用相同 payload 调用上述四个官方端点，固定模型、`top_n`、timeout、并发和测试窗口，并保存 HTTP 状态与响应快照。若官方 Search 页面要求 key，使用有效测试账户；没有有效账户就将该组标记为“未测”，而不是用 402 作为相关性分数。

## 推荐路线与不应宣称的事

**优先本地**：敏感文本和 URL 不可外发、离线或弱网 Agent、需要零按量服务费、需要自定义抽取/搜索源/缓存策略、可接受维护 GPU/容器的团队。Embeddings、Reranker、Reader、Deep 和工具编排均可作为本地能力，但生产前必须锁定真实模型 backend 并建立质量集。

**优先官方云服务**：需要托管搜索与抓取覆盖、官方模型/ReaderLM、供应商弹性和集中运维、团队不希望管理模型/GPU/搜索源，且网络、鉴权、数据合规和费用可接受的团队。官方端点是首选服务契约，版本、限制和价格应以官方页面和账户控制台为准。

**不应宣称**：不能说“jina-local 就是官方 Jina API”；不能说 21 个工具名相同就有 21 个官方能力的实现等价；不能说 92 tests passed、5/5 PASS、固定 toy 数据 top1 100%、hash fallback 或 402 时本地成功率 100% 就证明质量超过官方；不能把本地缓存 0 秒、单机显存估算或历史价格字符串当作官方 SLA、普适成本或跨环境性能结论。准确的表述应是：**jina-local 提供 Jina 风格 MCP 接口和一组可离线部署的本地后端，在明确的控制变量和数据集上可作为替代候选；是否达到官方服务的任务质量与运营要求，必须由同输入、同模型、同统计协议的独立复测决定。**

## 主要本地来源索引

- `mcp-gateway/src/server.py:109-220`：FastMCP、传输和工具注册。
- `mcp-gateway/src/gateway.py:9-146`、`:149-240`：模块委托、别名和本地入口。
- `mcp-gateway/src/reader.py:60-82`、`:123-231`、`:234-240`：抓取、Markdown 和抽取。
- `mcp-gateway/src/search.py:1`、`:108-187`：搜索聚合、词法排序和缓存。
- `mcp-gateway/src/search_deep.py:1-3`、`:121-142`、`:205-229`：Deep 编排和 fallback。
- `mcp-gateway/src/search_academic.py:1-9`、`:73-143`：学术、图片和截图工具。
- `mcp-gateway/src/embeddings.py:1-5`、`:26-42`、`:203-220`：模型、fallback、懒加载和分批。
- `mcp-gateway/src/reranker.py:1-7`、`:29-41`、`:200-229`：CrossEncoder、余弦 fallback 和分批。
- `mcp-gateway/src/utils.py:1-8`、`:117-219`：工具及 embedding 去重逻辑。
- `docker-compose.yml:1-40`、`:62-120`：TEI、Reader、Search、Qdrant、GPU 和卷。
- `scripts/bench_reader.py:21-35`、`:132-188`；`scripts/bench_search.py:24-75`、`:123-170`；`scripts/bench_embeddings.py:32-43`、`:93-144`；`scripts/bench_reranker.py:33-120`：现有 bench 输入和指标。
- `docs/bench-full.md:3-16`、`:30-85`、`:115-145`：现有总评及其局限的原始数字。
- `tests/test_mcp_compatibility.py:11-59`、`:129-170` 及 `tests/` 其余 Reader/Search/Deep/Embeddings/Reranker/Utils/Compose 测试：契约和系统回归边界。
