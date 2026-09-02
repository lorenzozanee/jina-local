#!/usr/bin/env python3
"""clean_cache.py: 清理 /tmp/opencode/jina-local 缓存

策略（与 AGENTS.md 第9条 opencode.db 超过10G 清理思想一致）：
- 超过 7 天（mtime > 7d）的文件删除
- 超过 10G 总量时，按 mtime 最旧优先删除，直到 <10G
- 保留最近 100 文件（最活跃，不删）
- 按 mtime 排序，兼顾 embed-*.npy / rerank-*.json / *.md / gpu-stats.json（后者常驻不删）

用法:
  python scripts/clean_cache.py            # 干跑 + 执行
  python scripts/clean_cache.py --dry-run  # 仅预览
  python scripts/clean_cache.py --cache-dir /tmp/opencode/jina-local --max-size-gb 10 --keep 100 --days 7
"""
import argparse
import pathlib
import time
import os

DEFAULT_CACHE = pathlib.Path("/tmp/opencode/jina-local")
KEEP_FILES = {"gpu-stats.json", "bench-gpu.json"}  # 常驻不参与计数
MAX_SIZE_GB = 10
KEEP_N = 100
DAYS = 7

def _file_age_days(p: pathlib.Path) -> float:
    try:
        mtime = p.stat().st_mtime
        return (time.time() - mtime) / 86400
    except Exception:
        return 0

def clean(cache_dir: pathlib.Path = DEFAULT_CACHE, max_size_gb: float = MAX_SIZE_GB, keep_n: int = KEEP_N, days: int = DAYS, dry_run: bool = False):
    cache_dir = pathlib.Path(cache_dir)
    if not cache_dir.exists():
        print(f"[clean] cache dir not exist: {cache_dir}")
        return {"deleted": [], "kept": [], "total_bytes": 0}
    all_files = [p for p in cache_dir.iterdir() if p.is_file()]
    # exclude keep files from deletion candidates but count
    candidates = [p for p in all_files if p.name not in KEEP_FILES]
    # sort newest first
    candidates_sorted = sorted(candidates, key=lambda p: p.stat().st_mtime, reverse=True)
    keep_set = set(candidates_sorted[:keep_n]) if keep_n > 0 else set()
    total_bytes = sum(p.stat().st_size for p in all_files if p.exists())
    max_bytes = int(max_size_gb * 1024**3)
    to_delete: list[pathlib.Path] = []
    # 7天过期
    cutoff = time.time() - days * 86400
    for p in candidates_sorted[keep_n:]:
        try:
            if p.stat().st_mtime < cutoff:
                to_delete.append(p)
        except Exception:
            pass
    # 超10G 按最旧删除
    # re-sort to_delete candidates by mtime oldest first for size control
    remaining_after_age = [p for p in candidates if p not in to_delete]
    remaining_bytes = sum(p.stat().st_size for p in remaining_after_age if p.exists()) + sum(p.stat().st_size for p in cache_dir.glob("*") if p.name in KEEP_FILES and p.exists())
    # if still over, delete oldest beyond keep_n
    if remaining_bytes > max_bytes:
        # candidates beyond keep_n sorted oldest first
        oldest_first = sorted([p for p in candidates if p not in to_delete and p not in keep_set], key=lambda p: p.stat().st_mtime)
        for p in oldest_first:
            if remaining_bytes <= max_bytes:
                break
            to_delete.append(p)
            try:
                remaining_bytes -= p.stat().st_size
            except Exception:
                pass
    # also ensure if total initial > max and keep_n still large, delete even within keep? no, keep_n is hard retention
    # perform deletion
    deleted = []
    deleted_bytes = 0
    for p in to_delete:
        try:
            sz = p.stat().st_size if p.exists() else 0
            if not dry_run:
                p.unlink()
            deleted.append(str(p))
            deleted_bytes += sz
            print(f"[clean] {'would delete' if dry_run else 'deleted'} {p.name} {sz/1024:.1f}KB age={_file_age_days(p):.1f}d")
        except Exception as e:
            print(f"[clean] fail {p}: {e}")
    kept = [str(p) for p in all_files if str(p) not in deleted]
    final_bytes = total_bytes - deleted_bytes
    print(f"[clean] total {total_bytes/1024/1024:.2f}MB -> {final_bytes/1024/1024:.2f}MB, deleted {len(deleted)} files ({deleted_bytes/1024/1024:.2f}MB), kept {len(kept)} (incl {keep_n} most recent + {len(KEEP_FILES)} protected)")
    return {"deleted": deleted, "kept": kept, "total_bytes_before": total_bytes, "total_bytes_after": final_bytes, "deleted_bytes": deleted_bytes, "dry_run": dry_run}

def main():
    ap = argparse.ArgumentParser(description="clean /tmp/opencode/jina-local cache")
    ap.add_argument("--cache-dir", default=str(DEFAULT_CACHE))
    ap.add_argument("--max-size-gb", type=float, default=MAX_SIZE_GB)
    ap.add_argument("--keep", type=int, default=KEEP_N)
    ap.add_argument("--days", type=int, default=DAYS)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    clean(pathlib.Path(args.cache_dir), args.max_size_gb, args.keep, args.days, args.dry_run)

if __name__ == "__main__":
    main()
