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

