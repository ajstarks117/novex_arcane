"""
Validator Agent — runs patch_diff inside a sandbox and reports results.

Ajaya's sandbox_runner.py will be wired in here once his Docker branch lands.
For now this skeleton satisfies the contract so the LangGraph flow can execute.

Contract (from Ajaya's spec):
  Input:  state['patch_diff'], state['commit_sha']
  Output: state['tests_passed']       (bool)
          state['retry_count']        (int, incremented on failure)
          state['validator_summary']  (str, one-liner for Rishi's PR body)
          state['timeout']            (bool)
"""

import logging

logger = logging.getLogger(__name__)


def run_validator(state: dict) -> dict:
    """
    Validates the proposed patch by running tests inside a sandbox.

    Currently a skeleton that always passes. Once Ajaya's Docker sandbox
    branch (feat/ajaya-docker) is merged, this will call sandbox_runner.py
    to actually execute pytest inside a container.
    """
    patch_diff = state.get("patch_diff", "")
    commit_sha = state.get("commit_sha", "unknown")
    retry_count = state.get("retry_count", 0)

    logger.info(
        f"[Validator] Running validation for commit {commit_sha[:7]} "
        f"(attempt {retry_count + 1})"
    )

    # ----- placeholder logic — swap for real sandbox call -----
    try:
        # TODO: Replace with Ajaya's sandbox_runner once merged
        # from scripts.sandbox_runner import run_in_sandbox
        # result = run_in_sandbox(patch_diff, commit_sha)

        # Skeleton: assume tests pass so the full loop can be demoed
        tests_passed = True
        timeout = False
        summary = (
            f"All tests passed for commit {commit_sha[:7]} "
            f"(attempt {retry_count + 1})"
        )

    except Exception as e:
        logger.error(f"[Validator] Sandbox error: {e}")
        tests_passed = False
        timeout = "timeout" in str(e).lower()
        summary = f"Validation failed: {e}"

    # ----- build return state -----
    return {
        **state,
        "tests_passed": tests_passed,
        "retry_count": retry_count + 1,
        "validator_summary": summary,
        "timeout": timeout,
    }
