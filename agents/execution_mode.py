"""ARCANE Execution Mode Manager

Supports dual-mode execution:
- 'local': Requires Docker daemon and runs full isolated sandbox workflows.
- 'hosted': Runs on cloud platforms (e.g., Render) without Docker. Uses GitHub API
            inspection, real LLM patch generation, static syntax validation, and draft PRs.
- 'auto' (default): Probes Docker daemon responsiveness with a short timeout and selects
                    'local' if usable, or 'hosted' otherwise without crashing.
"""

import os
import subprocess
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# In-memory cache for Docker daemon availability check: Optional[bool]
_DOCKER_AVAILABLE_CACHE: Optional[bool] = None


def is_docker_available(timeout: float = 2.0, force_probe: bool = False) -> bool:
    """Checks whether the Docker daemon is installed AND actively running.

    Uses `docker info` with a short timeout.
    Result is cached in-memory unless force_probe is True.
    """
    global _DOCKER_AVAILABLE_CACHE
    if _DOCKER_AVAILABLE_CACHE is not None and not force_probe:
        return _DOCKER_AVAILABLE_CACHE

    try:
        res = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        is_ok = (res.returncode == 0)
        _DOCKER_AVAILABLE_CACHE = is_ok
        if is_ok:
            logger.info("[ExecutionMode] Docker daemon detected and responsive.")
        else:
            logger.info("[ExecutionMode] Docker command exited non-zero; daemon unavailable.")
        return is_ok
    except (FileNotFoundError, subprocess.SubprocessError, Exception) as exc:
        logger.info(f"[ExecutionMode] Docker unavailable ({exc.__class__.__name__}: {exc})")
        _DOCKER_AVAILABLE_CACHE = False
        return False


def reset_docker_cache() -> None:
    """Resets the Docker probe cache (useful for testing)."""
    global _DOCKER_AVAILABLE_CACHE
    _DOCKER_AVAILABLE_CACHE = None


def get_execution_mode(force_probe: bool = False) -> str:
    """Returns 'local' or 'hosted' based on ARCANE_EXECUTION_MODE and Docker status.

    - ARCANE_EXECUTION_MODE='local':
        Requires Docker daemon. Raises RuntimeError if unavailable.
    - ARCANE_EXECUTION_MODE='hosted':
        Forces hosted mode (never calls Docker).
    - ARCANE_EXECUTION_MODE='auto' (or unset):
        Probes Docker. Uses 'local' if available, otherwise 'hosted'.
    """
    configured = os.getenv("ARCANE_EXECUTION_MODE", "auto").strip().lower()

    if configured == "hosted":
        return "hosted"

    if configured == "local":
        if not is_docker_available(force_probe=force_probe):
            raise RuntimeError(
                "ARCANE_EXECUTION_MODE is set to 'local', but the Docker daemon is not "
                "installed, running, or responsive. Please start Docker Desktop/daemon "
                "or set ARCANE_EXECUTION_MODE=auto or ARCANE_EXECUTION_MODE=hosted."
            )
        return "local"

    # 'auto' or fallback
    if is_docker_available(force_probe=force_probe):
        return "local"
    return "hosted"


def is_hosted_mode() -> bool:
    """Convenience helper returning True if current execution mode is hosted."""
    return get_execution_mode() == "hosted"


def is_patch_memory_enabled() -> bool:
    """Returns True if ChromaDB and embedding models are allowed to load.

    To stay strictly within Render's 512 MB RAM limit, patch memory (ChromaDB +
    sentence-transformers + PyTorch, which consumes ~420 MB RSS on import) is
    DISABLED in hosted mode.
    Can also be explicitly disabled via ARCANE_DISABLE_CHROMA=1.
    """
    if is_hosted_mode():
        return False
    if os.getenv("ARCANE_DISABLE_CHROMA", "").strip().lower() in ("1", "true", "yes"):
        return False
    return True


def get_memory_usage_mb() -> float:
    """Returns current process Resident Set Size (RSS) memory in MB."""
    try:
        import psutil
        return psutil.Process().memory_info().rss / (1024 * 1024)
    except Exception:
        try:
            import resource
            # ru_maxrss is in KB on Linux, bytes on macOS
            return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0
        except Exception:
            return 0.0


def log_memory_usage(label: str = "Memory Check") -> float:
    """Logs current process RSS memory (MB) at INFO level and returns the value."""
    mb = get_memory_usage_mb()
    logger.info(f"[Memory] {label}: {mb:.1f} MB RSS")
    return mb


def trigger_garbage_collection() -> float:
    """Runs Python garbage collection to immediately free unreferenced buffers and objects."""
    import gc
    gc.collect()
    mb = get_memory_usage_mb()
    logger.info(f"[Memory] Post-GC: {mb:.1f} MB RSS")
    return mb


