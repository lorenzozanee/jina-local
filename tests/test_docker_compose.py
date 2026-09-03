"""docker-compose.yml 契约测试

验证：
- 定义 embeddings/reranker/reader/search 四服务
- 使用 GPU (deploy.resources.reservations.devices 或 runtime: nvidia)
- 路径为 ~/jina-local 非 worktree
TDD 红阶段：当前为骨架注释，全部应 FAIL
"""
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "docker-compose.yml"
HOME_JINA_LOCAL = pathlib.Path.home() / "jina-local"  # /home/cc/jina-local
# 历史误用路径：worktree 下的 jina-local（不应存在）
WORKTREE_CANDIDATE = pathlib.Path("/home/cc/autonomous-worker/asset-workflow/.worktrees/issue-8-research/jina-local")


def _active_lines() -> list[str]:
    """返回 docker-compose.yml 中非注释、非空的有效行"""
    assert COMPOSE.exists(), f"功能缺失: {COMPOSE} 不存在"
    lines = COMPOSE.read_text(encoding="utf-8").splitlines()
    active = [l for l in lines if l.strip() and not l.strip().startswith("#")]
    return active


def _active_text() -> str:
    return "\n".join(_active_lines())


def test_compose_file_exists_at_home_jina_local():
    """docker-compose.yml 必须存在于 ~/jina-local（即 /home/cc/jina-local）"""
    assert HOME_JINA_LOCAL.exists(), f"功能缺失: 家目录 {HOME_JINA_LOCAL} 不存在"
    assert COMPOSE.exists(), f"功能缺失: {COMPOSE} 不存在，期望位于 ~/jina-local/docker-compose.yml"
    assert COMPOSE.is_file()


def test_compose_path_not_in_worktree():
    """项目根必须为 ~/jina-local，而非 worktree 临时目录"""
    # ROOT 推导自 tests/ 上一级，应等于 ~/jina-local
    assert ROOT.resolve() == HOME_JINA_LOCAL.resolve(), (
        f"功能缺失: 测试根 {ROOT.resolve()} != 家目录全局路径 {HOME_JINA_LOCAL.resolve()}，"
        f"不应在 worktree 下创建 jina-local"
    )
    # worktree 下不应存在 jina-local 副本
    assert not WORKTREE_CANDIDATE.exists(), (
        f"功能缺失: 不应在 worktree 路径 {WORKTREE_CANDIDATE} 存在 jina-local，应仅在 ~/jina-local"
    )


def test_compose_defines_embeddings_service():
    """必须定义 embeddings 服务"""
    text = _active_text()
    assert "embeddings:" in text, "功能缺失: docker-compose.yml 未定义 embeddings 服务（当前仅注释占位）"


def test_compose_defines_reranker_service():
    """必须定义 reranker 服务"""
    text = _active_text()
    assert "reranker:" in text, "功能缺失: docker-compose.yml 未定义 reranker 服务"


def test_compose_defines_reader_service():
    """必须定义 reader 服务"""
    text = _active_text()
    # 兼容 reader / fetch / extractor 命名，但规范要求 reader
    assert "reader:" in text, "功能缺失: docker-compose.yml 未定义 reader 服务"


def test_compose_defines_search_service():
    """必须定义 search 服务"""
    text = _active_text()
    assert "search:" in text, "功能缺失: docker-compose.yml 未定义 search 服务"


def test_compose_services_use_gpu():
    """服务必须配置 GPU（deploy.resources.reservations.devices driver nvidia 或 runtime: nvidia / gpus）"""
    text = _active_text()
    # 仅在有效行中查找，避免注释中的示例被误判为通过
    has_deploy_gpu = "driver: nvidia" in text and "capabilities:" in text and "gpu" in text
    has_runtime = "runtime: nvidia" in text
    has_gpus = "gpus:" in text
    assert has_deploy_gpu or has_runtime or has_gpus, (
        "功能缺失: docker-compose.yml 未配置 GPU，期望 deploy.resources.reservations.devices "
        "driver: nvidia 或 runtime: nvidia / gpus；当前仅注释，占位未生效"
    )


def test_compose_has_services_top_level():
    """顶层需包含 services: 段（非注释）"""
    text = _active_text()
    assert "services:" in text, "功能缺失: docker-compose.yml 缺少顶层 services: 定义（当前被注释）"


def test_compose_uses_configurable_search_port_and_reader_token():
    """Search 与 Reader 必须由 .env 驱动，避免端口冲突或 Reader 只绑定容器回环。"""
    text = _active_text()
    assert '${SEARXNG_PORT:-8081}:8080' in text
    assert 'CRAWL4AI_API_TOKEN: "${CRAWL4AI_API_TOKEN:?' in text
    assert 'SEARXNG_PORT: "8080"' in text
    assert './searxng:/etc/searxng' in text
    assert 'read_only: true' not in text
    assert 'cap_drop:' not in text
    settings = ROOT / 'searxng' / 'settings.yml'
    assert settings.exists()
    assert 'formats:' in settings.read_text(encoding='utf-8')
    assert '- json' in settings.read_text(encoding='utf-8')
