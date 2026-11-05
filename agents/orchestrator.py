"""
ARCANE Orchestrator — Phase 1 LangGraph State Machine Skeleton

States:
  IDLE → ANALYZING → BISECTING → PATCHING → PROPAGATING →
  CONFLICT_CHECKING → VALIDATING → GENERATING_TEST → CREATING_PR → DONE
                                                                    ↘ ESCALATED

Conditional edges:
  • PATCHING      → ESCALATED           if retry_count >= 3
  • VALIDATING    → GENERATING_TEST     if tests_passed == True
  • VALIDATING    → PATCHING            if tests_passed == False and retry_count < 3
  • VALIDATING    → ESCALATED           if retry_count >= 3
"""

import asyncio
import logging
from datetime import datetime
from typing import TypedDict, Optional, Any

try:
    from agents.validator_agent import validate, capture_baseline
    from agents.regression_test_generator import generate_regression_test
except ImportError as _e:
    logger = logging.getLogger(__name__)
    logger.warning(f"[ARCANE] Validator imports not available: {_e}")
    validate = capture_baseline = generate_regression_test = None

from langgraph.graph import StateGraph, END

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MAX_RETRIES = 3


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  State schema
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class ArcaneState(TypedDict, total=False):
    # ── Incoming (webhook payload) ──
    event: dict                         # raw CI failure dict
    repo_full_name: str
    commit_sha: str
    failure_log: str

    # ── ANALYZING outputs ──
    failing_test: str
    failing_file: str
    failing_line: int
    root_cause_summary: str
    suspected_function: str

    # ── BISECTING outputs ──
    bisect_intent_report: str

    # ── PATCHING outputs ──
    patch_diff: str
    retry_count: int

    # ── PROPAGATING outputs ──
    cascade_failure: bool
    cascade_report: str

    # ── CONFLICT_CHECKING outputs ──
    conflict_detected: bool

    # ── VALIDATING outputs ──
    tests_passed: bool
    confidence_score: float

    # ── GENERATING_TEST outputs ──
    regression_test_code: str

    # ── CREATING_PR outputs ──
    pr_url: Optional[str]

    # ── Meta ──
    error: Optional[str]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Node functions  (mock data — every node returns plausible hardcoded values)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def idle_node(state: ArcaneState) -> ArcaneState:
    """IDLE — receives the raw CI failure event and seeds the state."""
    logger.info("[IDLE] Received CI failure event")
    event = state.get("event", {})
    seeded_state = {
        **state,
        "repo_full_name": event.get("repo_full_name", state.get("repo_full_name", "")),
        "commit_sha": event.get("commit_sha", state.get("commit_sha", "")),
        "failure_log": event.get("failure_log", state.get("failure_log", "")),
    }
    # Capture baseline BEFORE any patch is applied
    if capture_baseline:
        seeded_state = capture_baseline(seeded_state)
    return seeded_state


from agents.analyst_agent import analyze as run_analyst

def analyzing_node(state: ArcaneState) -> ArcaneState:
    """ANALYZING — parses failure log to extract test name, file, line, root cause."""
    logger.info("[ANALYZING] Delegating to Analyst Agent")
    return run_analyst(state)


def bisecting_node(state: ArcaneState) -> ArcaneState:
    """BISECTING — narrows down the commit that introduced the failure."""
    logger.info("[BISECTING] Running git-bisect analysis")
    return {
        **state,
        "bisect_intent_report": (
            f"Bisect identified commit {state.get('commit_sha', '???')[:7]} as the "
            f"first bad commit. Function `{state.get('suspected_function', '?')}` "
            f"in `{state.get('failing_file', '?')}` was modified."
        ),
    }


from agents.patch_generator import generate_patch as run_patch_generator

def patching_node(state: ArcaneState) -> ArcaneState:
    """PATCHING — generates a code patch to fix the suspected function."""
    logger.info("[PATCHING] Delegating to Patch Generator")
    return run_patch_generator(state)


def propagating_node(state: ArcaneState) -> ArcaneState:
    """PROPAGATING — checks for cascade / downstream failures."""
    logger.info("[PROPAGATING] Checking downstream impact")
    return {
        **state,
        "cascade_failure": False,
        "cascade_report": "No downstream modules affected by this patch.",
    }


def conflict_checking_node(state: ArcaneState) -> ArcaneState:
    """CONFLICT_CHECKING — detects merge conflicts with main branch."""
    logger.info("[CONFLICT_CHECKING] Verifying merge compatibility")
    return {
        **state,
        "conflict_detected": False,
    }


def validating_node(state: ArcaneState) -> ArcaneState:
    """VALIDATING — applies patch in Docker sandbox and runs full pytest suite."""
    retry = state.get("retry_count", 0)
    logger.info(f"[VALIDATING] Running test suite (attempt {retry + 1})")
    if validate:
        updated = validate(state)
        return {**state, **updated}
    # Fallback mock if validator not available
    passed = retry <= 1
    return {**state, "tests_passed": passed, "confidence_score": 0.95 if passed else 0.30}


def generating_test_node(state: ArcaneState) -> ArcaneState:
    """GENERATING_TEST — synthesizes a regression test via Claude LLM."""
    logger.info("[GENERATING_TEST] Producing regression test via LLM")
    if generate_regression_test:
        updated = generate_regression_test(state)
        return {**state, **updated}
    # Fallback mock if generator not available
    return {**state, "regression_test_code": "def test_placeholder(): pass"}


def creating_pr_node(state: ArcaneState) -> ArcaneState:
    """CREATING_PR — opens a pull request on GitHub with the patch + test."""
    logger.info("[CREATING_PR] Opening pull request")
    sha = state.get("commit_sha", "unknown")[:7]
    return {
        **state,
        "pr_url": f"https://github.com/{state.get('repo_full_name', 'org/repo')}/pull/mock-{sha}",
    }


def done_node(state: ArcaneState) -> ArcaneState:
    """DONE — terminal success state."""
    logger.info(f"[DONE] Workflow complete — PR: {state.get('pr_url', 'N/A')}")
    return state


def escalated_node(state: ArcaneState) -> ArcaneState:
    """ESCALATED — retries exhausted; needs human review."""
    logger.warning(
        f"[ESCALATED] Auto-repair failed after {state.get('retry_count', 0)} attempts. "
        f"Commit: {state.get('commit_sha', '?')[:7]}"
    )
    return {
        **state,
        "error": (
            f"Escalated after {state.get('retry_count', 0)} retries — "
            f"human review required for {state.get('failing_test', 'unknown test')}"
        ),
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Conditional edge functions
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def after_patching(state: ArcaneState) -> str:
    """After PATCHING: escalate if retry cap hit, else continue to PROPAGATING."""
    if state.get("retry_count", 0) >= MAX_RETRIES:
        logger.warning("[PATCHING] Retry cap reached — escalating")
        return "escalated"
    return "propagating"


def after_validating(state: ArcaneState) -> str:
    """After VALIDATING: route based on test results + retry count."""
    if state.get("tests_passed"):
        return "generating_test"
    if state.get("retry_count", 0) >= MAX_RETRIES:
        logger.warning("[VALIDATING] Retry cap reached — escalating")
        return "escalated"
    logger.info("[VALIDATING] Tests failed — looping back to PATCHING")
    return "patching"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Build & compile the graph
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def build_graph() -> StateGraph:
    builder = StateGraph(ArcaneState)

    # ── Register nodes ──
    builder.add_node("idle", idle_node)
    builder.add_node("analyzing", analyzing_node)
    builder.add_node("bisecting", bisecting_node)
    builder.add_node("patching", patching_node)
    builder.add_node("propagating", propagating_node)
    builder.add_node("conflict_checking", conflict_checking_node)
    builder.add_node("validating", validating_node)
    builder.add_node("generating_test", generating_test_node)
    builder.add_node("creating_pr", creating_pr_node)
    builder.add_node("done", done_node)
    builder.add_node("escalated", escalated_node)

    # ── Entry point ──
    builder.set_entry_point("idle")

    # ── Linear edges ──
    builder.add_edge("idle", "analyzing")
    builder.add_edge("analyzing", "bisecting")
    builder.add_edge("bisecting", "patching")

    # ── Conditional: PATCHING → PROPAGATING or ESCALATED ──
    builder.add_conditional_edges(
        "patching",
        after_patching,
        {
            "propagating": "propagating",
            "escalated": "escalated",
        },
    )

    # ── Linear edges continued ──
    builder.add_edge("propagating", "conflict_checking")
    builder.add_edge("conflict_checking", "validating")

    # ── Conditional: VALIDATING → GENERATING_TEST / PATCHING / ESCALATED ──
    builder.add_conditional_edges(
        "validating",
        after_validating,
        {
            "generating_test": "generating_test",
            "patching": "patching",
            "escalated": "escalated",
        },
    )

    # ── Linear edges to terminal states ──
    builder.add_edge("generating_test", "creating_pr")
    builder.add_edge("creating_pr", "done")
    builder.add_edge("done", END)
    builder.add_edge("escalated", END)

    return builder.compile()


# Pre-compiled graph — importable as `from agents.orchestrator import graph`
graph = build_graph()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Pipeline entry point  (async — callable from FastAPI event loop)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def run_pipeline(event: dict) -> dict:
    """
    Accepts a parsed webhook event dict from the asyncio queue and drives
    the full LangGraph state machine to completion.

    Logs every state transition in the format:
        [HH:MM:SS] STATE: {state_name} | retry: {retry_count}

    Returns the final state dict.
    """
    initial_state: ArcaneState = {
        "event": event,
        "repo_full_name": event.get("repo_full_name", ""),
        "commit_sha": event.get("commit_sha", ""),
        "failure_log": event.get("failure_log", ""),
        "retry_count": 0,
    }

    ts = datetime.now().strftime("%H:%M:%S")
    logger.info(f"[{ts}] STATE: __start__ | retry: 0")

    final_state = {}

    # astream yields {node_name: state_after_node} for each step
    async for step_output in graph.astream(initial_state):
        for node_name, node_state in step_output.items():
            retry = node_state.get("retry_count", 0) if isinstance(node_state, dict) else 0
            ts = datetime.now().strftime("%H:%M:%S")
            logger.info(f"[{ts}] STATE: {node_name} | retry: {retry}")
            if isinstance(node_state, dict):
                final_state = node_state

    ts = datetime.now().strftime("%H:%M:%S")
    logger.info(f"[{ts}] STATE: __end__ | retry: {final_state.get('retry_count', 0)}")

    return final_state


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Verification  (run this file directly: python -m agents.orchestrator)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def _verify():
    """Runs all prompt-2 verification checkpoints."""
    drawable = graph.get_graph()

    # ── 1. Visualise ──
    print("\n" + "=" * 70)
    print("  [OK] CHECKPOINT: LangGraph visualiser produces diagram")
    print("=" * 70)
    drawable.print_ascii()
    print("\n--- Mermaid ---")
    print(drawable.draw_mermaid())

    # ── 2. Happy path -> DONE ──
    print("\n" + "=" * 70)
    print("  [OK] CHECKPOINT: Mock event -> run_pipeline -> reaches DONE")
    print("=" * 70)
    result = await run_pipeline({
        "repo_full_name": "aryanketkar-15/ARCANE_Nexus2.0",
        "commit_sha": "a1b2c3d4e5f6789",
        "failure_log": "FAILED test_payment_processing -- AssertionError",
    })
    print(f"\n  tests_passed      : {result.get('tests_passed')}")
    print(f"  confidence_score  : {result.get('confidence_score')}")
    print(f"  retry_count       : {result.get('retry_count')}")
    print(f"  pr_url            : {result.get('pr_url')}")
    print(f"  error             : {result.get('error', 'None')}")
    assert result.get("pr_url"), "FAIL: expected pr_url in DONE state"
    assert result.get("tests_passed") is True, "FAIL: expected tests_passed=True"
    print("  [PASS] DONE path verified")

    # ── 3. Escalation path -> ESCALATED after 3 retries ──
    print("\n" + "=" * 70)
    print("  [OK] CHECKPOINT: Retry counter -> ESCALATED after 3 retries")
    print("=" * 70)
    # Force failures by starting retry_count high so patching hits cap
    esc_state: ArcaneState = {
        "event": {
            "repo_full_name": "aryanketkar-15/ARCANE_Nexus2.0",
            "commit_sha": "deadbeef1234567",
            "failure_log": "FAILED test_checkout -- TypeError",
        },
        "retry_count": 2,  # next patch makes it 3 -> escalate
    }
    final = {}
    async for step_output in graph.astream(esc_state):
        for node_name, node_state in step_output.items():
            retry = node_state.get("retry_count", 0) if isinstance(node_state, dict) else 0
            ts = datetime.now().strftime("%H:%M:%S")
            logger.info(f"[{ts}] STATE: {node_name} | retry: {retry}")
            if isinstance(node_state, dict):
                final = node_state

    print(f"\n  retry_count       : {final.get('retry_count')}")
    print(f"  error             : {final.get('error', 'None')}")
    assert final.get("retry_count", 0) >= MAX_RETRIES, "FAIL: retry_count should be >= 3"
    assert final.get("error"), "FAIL: expected error message in ESCALATED state"
    print("  [PASS] ESCALATED path verified")

    print("\n" + "=" * 70)
    print("  [DONE] ALL PROMPT-2 VERIFICATION CHECKPOINTS PASSED")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(_verify())
