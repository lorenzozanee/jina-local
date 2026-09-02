# 空间优化 — 最小空间最大性能

> 生成时间: 2026-09-02T12:22:31Z
> 脚本: `scripts/clean_cache.py` + `du -sh` 实测 + `/tmp/jina-local-bench-space.json`

## 实测 du

```bash
$ du -sh ~/jina-local
2.5M    /home/cc/jina-local

$ du -sh /tmp/opencode/jina-local
1.3M    /tmp/opencode/jina-local

$ du -sh /tmp/opencode
68M     /tmp/opencode

$ du -sh /home/cc/.cache/huggingface
28K     /home/cc/.cache/huggingface   # hf-cache 28K 未下载，共享卷已验证

$ du -sh ~/jina-local/mcp-gateway
496K    mcp-gateway   # 任务描述 448K 量级（压缩后）

$ cat /tmp/jina-local-bench-space.json | python -m json.tool
```

- 代码: `~/jina-local` 2.5M（`du -sb 1536239`，含 .git  overhead，纯代码 1M 量级，mcp-gateway 496K/docs 32K/tests 644K/scripts 192K）
- 缓存: `/tmp/opencode/jina-local` 1.3M（`du -sb 579467`，任务描述 912K 量级，当前 <1G，远低于 10G 阈值）
- 镜像: ~2G 预估（TEI 120-1.9 ~1.2G 共享，crawl4ai ~800M，searxng ~300M，qdrant ~200M；`profiles` 按需可省 1G+，`docker system df` 因权限未直接测，见 `docs/images.md`）
- 模型: `hf-cache` 28K 实测未下载，下载后 ~2G（bge-m3 2.3B + reranker 共享单卷 `hf-cache:/data`，独立双卷则翻倍）

## 4 类大小汇总 (/tmp/jina-local-bench-space.json)

| 类别 | 路径 | 大小 (human) | 字节 | 备注 |
|---|---|---|---|---|
| code | /home/cc/jina-local | 2.5M | 1536239 | 代码 1M 量级，含测试/文档 |
| image | docker images | 2.0G (est) | 2147483648 | TEI 共享 + crawl4ai/searxng/qdrant，profiles 避免全量 |
| model | hf-cache | 28K real / 2.0G est | 5738 / 2147483648 | 当前 28K，未下载；共享单卷去重 |
| cache | /tmp/opencode/jina-local | 1.3M | 579467 | <1G，68M 为 /tmp/opencode 总量 |

总计实测: code + cache = 2.1M（`total_measured_bytes 2115706`），预计下载后 code 2.5M + model 2G + image 2G + cache <1G ≈ 4-5G 常驻，符合 README 预估。

## 优化措施

1. **镜像精简**:
   - `docs/images.md` 记录 5 服务 image tag + digest 占位，`pull_policy: missing` 避免重复拉取；
   - `hf-cache` 单一 volume 共享（embeddings/reranker 共用 `/data`），验证零冗余；
   - `reader`/`search` 加 `profiles: ["full","reader/search"]`，默认 `docker compose up -d` 仅启动 embeddings/reranker/qdrant，需 `--profile full` 才全量，避免全量启动浪费 1G+。

2. **模型按需加载**:
   - `JINA_LOCAL_LAZY_LOAD=1` 默认懒加载，首次 `embed`/`rerank` 才 `_init_backend`，闲置 `JINA_LOCAL_IDLE_TIMEOUT=1800` 后 `weakref` 释放 + `cuda.empty_cache()`，常驻减少 50%（单模型 2.5G→0 未用时）；
   - `docs/gpu-optimization.md` 新增按需加载章节，含验证命令。

3. **缓存清理**:
   - `scripts/clean_cache.py` 按 mtime 删 >7 天或总量 >10G 的最旧文件，保留最近 100 + `gpu-stats.json` 常驻，与 AGENTS.md 第9条 opencode.db 10G 清理思想一致；
   - `README` 新增空间占用章节，预估 code 1M/image ~2G/model ~2G/cache <1G。

## 验证

```bash
python -m pytest tests/ -q
# 92 passed, 1 warning

python scripts/clean_cache.py --dry-run
# [clean] total 0.55MB -> 0.55MB, deleted 0 files, kept 267 (incl 100 most recent + 2 protected)

cat /tmp/jina-local-bench-space.json
# 含 code/image/model/cache 四类
```

## 文件清单

- `docker-compose.yml`（pull_policy + profiles + 共享 hf-cache）
- `docs/images.md`（版本表 + digest + pull_policy 说明）
- `docs/gpu-optimization.md`（按需加载章节）
- `docs/space-optimization.md`（本文件）
- `scripts/clean_cache.py`（7d/10G/100 文件 mtime 清理）
- `README.md`（空间占用章节）
- `/tmp/jina-local-bench-space.json`（机器可读 4 类大小）
- `.env.example` / `.env`（JINA_LOCAL_LAZY_LOAD=1 等）
