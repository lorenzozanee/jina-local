# GPU 检索链路分阶段计划

## 目标

在不降低主分支现有功能的前提下，把可本地推理的检索链路统一到 TEI GPU，并在服务可用时接入 Qdrant；控制批量、缓存和模型生命周期，降低 CPU 与系统内存占用。

## 基线

- 对照分支：`master`，提交 `283f720`。
- 基线测试：108 passed，2 failed；两个失败均为环境路径断言（`tests/test_docker_compose.py`、`tests/test_mcp_global.py`）。
- 当前已有：TEI Embeddings/Reranker 路由和 Qdrant Compose 服务声明。
- 当前缺口：`search_deep.py`、`utils.py` 未统一通过 Gateway 服务端路由；代码中没有 Qdrant 客户端适配层。

## 阶段一：统一推理路由

1. RED：测试 Deep Search、去重、分类调用可注入的 Gateway Embeddings/Reranker，而不是各自实现 CPU 路径。
2. GREEN：增加最小服务端路由接口，复用现有 TEI 优先的 Embeddings/Reranker。
3. 验证：单测、真实 TEI 调用、CPU/RAM/GPU 采样；结果必须不低于 master。
4. Review：独立 subagent 检查 fallback、错误传播、缓存和资源释放。

## 阶段二：Qdrant 混合检索

1. RED：测试 Qdrant 不可用时保留 master 行为，可用时返回向量候选并与关键词候选稳定融合。
2. GREEN：新增最小 Qdrant adapter，连接复用、超时、批量 upsert/search，禁止无界缓存。
3. 验证：Compose 实际服务、关闭 Qdrant 的降级、相关性/延迟/内存对比。
4. Review：独立 subagent 检查连接泄漏、索引一致性和 fallback 静默失败。

## 阶段三：Deep Search 全链路

1. RED：测试搜索 → Reader → Embedding → Reranker → 去重/分类统一走服务端，并保持返回契约。
2. GREEN：逐步接入 Qdrant 与 TEI，保留明确的能力边界和有限并发。
3. 验证：真实任务集与 master 对比，成功率、相关性、P50/P95、CPU/RAM/GPU、缓存命中率。
4. Review：独立 subagent 做 code review 和回归检查。

## 完成门禁

- 每一阶段必须先看到测试按预期失败，再写生产代码。
- 阶段验证未优于 master，不进入下一阶段。
- 最终执行 lint、typecheck（若项目提供）、全量 pytest、真实服务测试、资源采样和最终 code review。
- 不自动 commit、push；保持分支与主分支隔离。
