# GPU 最大化利用 — RTX 5070 12GB 显存预算与并发策略

> 硬件: NVIDIA GeForce RTX 5070 12GB (12227 MiB), 驱动 595.84, CUDA 13.2, Blackwell sm_120  
> 镜像: `ghcr.io/huggingface/text-embeddings-inference:120-1.9` (Blackwell 专用, CUDA 13.2 兼容), fallback `...:1.9`  
> 设备自动检测: `torch.cuda.is_available()` → `cuda` / `cuda:0`, 环境变量 `JINA_LOCAL_EMBEDDINGS_DEVICE` / `JINA_LOCAL_RERANKER_DEVICE` / `JINA_LOCAL_USE_GPU=0` 强制回退 cpu  
> 量化: `--dtype float16` + `model.half()` (≈50% 显存节省), 仅 cuda 设备生效

生成时间: `2026-09-02`

## 显存预算 (12GB)

| 组件 | 模型 | 精度 | 显存占用 | 说明 |
|---|---|---|---|---|
| embeddings | BAAI/bge-m3 (2.3B params) | float16 | ~2.5 GB | bge-m3 多语言 1024 维, 120-1.9 TEI 内置 FlashAttention, `max-batch-tokens 16384` |
| reranker | BAAI/bge-reranker-v2-m3 | float16 | ~1.5 GB | cross-encoder rerank, 共享 hf-cache 卷 |
| overhead | CUDA context + TEI 框架 | - | ~1.0 GB | `shm_size: 1g`, NCCL/cuBLAS 缓存 |
| **合计常驻** |  |  | **~5.0 GB** | 占 12GB 的 41% |
| **剩余** |  |  | **~7.0 GB** | 可跑 vLLM 8B Q4 (如 Qwen2.5-7B-GPTQ) 或并发批处理突发 |

验证:
```bash
python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'cpu')"
nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits
# 期望: torch cuda 可用时加载后 1-3GB 单模型, 双 TEI 常驻 ~5GB, 余量 7GB
# 实测 (hash fallback/无模型): 0 MB (cpu), 日志见 /tmp/opencode/jina-local/gpu-stats.json
cat /tmp/opencode/jina-local/gpu-stats.json | python -m json.tool
```

日志:
- 加载前后打印 `torch.cuda.memory_allocated()` / `memory_reserved()`
- 写入 `/tmp/opencode/jina-local/gpu-stats.json` (history 保留 50 条, 含 device/backend/dim/timestamp)
- TEI 容器内 `nvidia-smi` 应显示 1.5-2.5GB/模型, 非 cpu 时 0

## 并发策略

- **max-batch-tokens 16384**: 单请求按估算 `tokens≈len(text)/4` 切片, 避免 OOM, 超长文本分多批 `SentenceTransformer.encode` / `CrossEncoder.predict`
  - embeddings: `_batch_by_tokens(texts, 16384)` → 多次 `encode`
  - reranker: `_batch_by_tokens_pairs(query, docs, 16384)` → 多次 `predict`, 失败批回退 cosine
- **max-concurrent-requests 64**: TEI `--max-concurrent-requests 64` 配合 `shm_size: 1g`, 吞吐 > 100 QPS (batch 64×256 tokens)
- **runtime: nvidia 双配置**: 同时保留 `runtime: nvidia` (旧 docker-compose) 与 `deploy.resources.reservations.devices driver:nvidia` (v2), 兼容新旧
- **环境变量**: `HF_HUB_OFFLINE=0` 允许 TEI 拉模型, `CUDA_VISIBLE_DEVICES=0` 定卡, 本地 Python 端 `JINA_LOCAL_USE_GPU=0` 可强制 cpu 调试
- **reader 去 GPU**: `unclecode/crawl4ai` 仅 CPU, 避免抢占 7GB 余量给 vLLM

## docker-compose 变更

```yaml
embeddings:
  image: ghcr.io/huggingface/text-embeddings-inference:120-1.9  # Blackwell 120, fallback 1.9 见注释
  command: --model-id BAAI/bge-m3 --dtype float16 --max-batch-tokens 16384 --max-concurrent-requests 64
  runtime: nvidia
  shm_size: 1g
  environment: [HF_HUB_OFFLINE=0, CUDA_VISIBLE_DEVICES=0]
reranker:
  image: ghcr.io/huggingface/text-embeddings-inference:120-1.9
  command: --model-id BAAI/bge-reranker-v2-m3 --dtype float16 --max-batch-tokens 16384 --max-concurrent-requests 64
  runtime: nvidia
  shm_size: 1g
  environment: [HF_HUB_OFFLINE=0, CUDA_VISIBLE_DEVICES=0]
reader:
  # 已移除 deploy GPU, 仅 embeddings/reranker 占 GPU
```

## 按需加载（JINA_LOCAL_LAZY_LOAD=1 默认开启，减少常驻 50%）

> 环境变量 `JINA_LOCAL_LAZY_LOAD=1`（默认开启），`JINA_LOCAL_IDLE_TIMEOUT=1800`（秒，默认 30min）

- **懒加载**: `embeddings.py`/`reranker.py` 在 import 时不初始化模型（`_backend=None`），首次 `embed()`/`rerank()` 时才 `_init_backend()`（`SentenceTransformer`/`CrossEncoder` 或 hash/cosine fallback），避免常驻 ~4GB（bge-m3 2.5G+reranker 1.5G）未用即占。
- **闲置释放**: 每次调用 `_touch()` 记录 `monotonic`，下次调用前 `_maybe_release_idle()` 检查 `now - _last_used > _IDLE_TIMEOUT`，若超时则 `weakref.ref(_model)` 后 `_model=None; _backend=None; torch.cuda.empty_cache(); gc.collect()`，释放显存/内存，`_write_gpu_stats("embeddings_released_idle")` 记录。下次再调用自动重载。
- **weakref**: 释放时用 `weakref.ref` 保留弱引用，可探测是否已被 GC，强引用置空确保不常驻；hash fallback 无模型不触发释放。
- **环境控制**:
  - `JINA_LOCAL_LAZY_LOAD=1` 默认懒加载，常驻仅 Python 进程 ~50M，未加载模型时 0 GPU；
  - `JINA_LOCAL_LAZY_LOAD=0`  eager 模式，import 即 `_init_backend()`，适用于低延迟首请求；
  - `JINA_LOCAL_IDLE_TIMEOUT` 调整超时，`0` 表示永不释放，`60` 表示 1min 闲置即释放。
  - 兼容 `JINA_LOCAL_EMBEDDINGS_DEVICE`/`JINA_LOCAL_RERANKER_DEVICE`/`JINA_LOCAL_USE_GPU=0` 强制 cpu；
- **收益**: 仅 embeddings 或仅 reranker 场景可节省 50% 常驻（另一模型不加载）；全闲置 30min 后双模型释放，常驻接近 0 GPU，剩余 12GB 可供其他任务，符合"最小空间最大性能"。
- **实现位置**: `mcp-gateway/src/embeddings.py: _JINA_LAZY/_IDLE_TIMEOUT/_last_used/_model_ref/_touch/_maybe_release_idle/_release_backend/release_model`，`reranker.py` 同步；`get_backend()`/`embed()`/`rerank()` 均触发检查。

验证:
```bash
JINA_LOCAL_LAZY_LOAD=1 python -c "import sys; sys.path.insert(0,'mcp-gateway/src'); import embeddings; print(embeddings._backend) # None 未加载"
JINA_LOCAL_LAZY_LOAD=1 python -c "import sys; sys.path.insert(0,'mcp-gateway/src'); import embeddings; print(embeddings.embed(['hello'])) ; print(embeddings._backend)"
JINA_LOCAL_IDLE_TIMEOUT=2 python -c "import sys,time; sys.path.insert(0,'mcp-gateway/src'); import embeddings; embeddings.embed(['hi']); print('loaded',embeddings._backend); time.sleep(3); embeddings.embed(['hi again']); print('after idle',embeddings._backend)"
# 预期：首次前 backend None，首次后为 hash/hf，idle 超时后释放再加载
cat /tmp/opencode/jina-local/gpu-stats.json | python -c "import json,pathlib; d=json.loads(pathlib.Path('/tmp/opencode/jina-local/gpu-stats.json').read_text()); print([h['stage'] for h in d.get('history',[])][-5:])"
```

## 验证步骤 (TDD 保持 125 通过)

```bash
python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'cpu')"
python -m pytest tests/test_embeddings.py tests/test_reranker_extended.py -v  # GPU 不可用自动回退 cpu
python scripts/bench_embeddings.py   # 输出 /tmp/jina-local-bench-embeddings.json
python scripts/bench_reranker.py     # 输出 /tmp/jina-local-bench-reranker.json
# 汇总 GPU vs CPU
python -c "import json,torch; print(json.dumps({'cuda':torch.cuda.is_available(),'mem':torch.cuda.memory_allocated() if torch.cuda.is_available() else 0},indent=2))"
cat /tmp/jina-local-bench-gpu.json
nvidia-smi  # 期望 1-3GB 单模型, 5GB 双模型常驻
```

若 `torch.__version__` 为 `+cpu` (如当前 2.13.0+cpu) 则 `cuda.is_available()==False`, 自动回退 hash/cosine, 不破坏离线, bench 仍 PASS; 未来换 `torch==2.8+cu128` 即可自动启用 GPU 0 并记录 gpu-stats.
