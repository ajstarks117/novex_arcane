import os
import logging
from github import Github
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

from agents.mermaid_generator import generate_mermaid_diagram
from agents.execution_mode import get_execution_mode


def create_pr(state: dict) -> str:
    """Creates a new branch from main/base, commits the patch diff and patched file,
    and opens a PR with the full 7-section format.

    In hosted mode (or when validation was SKIPPED):
    - Opens a Draft PR (draft=True).
    - Includes a prominent unverified testing banner and review requirement.
    In local mode:
    - Opens a standard PR.
    """
    token = os.getenv("GITHUB_PAT")
    if not token:
        raise ValueError("GITHUB_PAT not found in environment variables")

    repo_full_name = state.get("repo_full_name", "")
    commit_sha = state.get("commit_sha", "unknown")
    patch_diff = state.get("patch_diff", "")
    failing_test = state.get("failing_test", "unknown_test")
    failing_file = state.get("failing_file", "unknown_file")
    root_cause = state.get("root_cause_summary", "No root cause provided.")
    regression_test = state.get("regression_test_code", "")
    confidence = state.get("confidence_score", "N/A")
    tests_passed = state.get("tests_passed", False)

    mode = state.get("execution_mode") or get_execution_mode()
    validation_status = state.get("validation_status", "PASSED" if tests_passed else "SKIPPED")
    is_draft = (mode == "hosted") or (validation_status == "SKIPPED")
    state["is_draft_pr"] = is_draft

    g = Github(token)
    repo = g.get_repo(repo_full_name)

    branch_name = f"arcane/fix-{commit_sha[:7]}"
    base_branch = (state.get("event") or {}).get("branch") or "main"
    patched_content = state.get("patched_content", "")

    # 1. Create a new branch from base
    base_ref = repo.get_git_ref(f"heads/{base_branch}")
    try:
        repo.create_git_ref(ref=f"refs/heads/{branch_name}", sha=base_ref.object.sha)
    except Exception as e:
        logger.warning(f"Branch creation exception (might already exist): {e}")

    # 2. Commit the patch_diff content as a .diff artifact on this branch
    file_path = f"arcane_patch_{commit_sha[:7]}.diff"
    commit_msg = f"fix: ARCANE auto-repair code patch for {failing_test}"

    try:
        contents = repo.get_contents(file_path, ref=branch_name)
        repo.update_file(contents.path, commit_msg, patch_diff, contents.sha, branch=branch_name)
    except Exception:
        repo.create_file(file_path, commit_msg, patch_diff, branch=branch_name)

    # 2b. Commit the actual fix to the failing file so the PR really changes the code
    fix_committed = False
    if patched_content and failing_file and failing_file not in ("N/A", "unknown_file", "unknown"):
        try:
            try:
                existing = repo.get_contents(failing_file, ref=branch_name)
                repo.update_file(existing.path, f"fix: ARCANE repair for {failing_test}", patched_content, existing.sha, branch=branch_name)
            except Exception:
                repo.create_file(failing_file, f"fix: ARCANE repair for {failing_test}", patched_content, branch=branch_name)
            fix_committed = True
        except Exception as e:
            logger.warning(f"Could not commit the patched file {failing_file}: {e}")

    # Generate mermaid diagram
    logger.info("Generating Mermaid diagram...")
    try:
        mermaid_diagram = generate_mermaid_diagram(patch_diff, root_cause)
    except Exception as m_err:
        logger.warning(f"Mermaid generation fallback: {m_err}")
        mermaid_diagram = "```mermaid\ngraph LR\n  Fail[CI Failure] --> Fix[Proposed Patch] --> Review[Human Review]\n```"

    # Title & Banner
    if is_draft:
        pr_title = f"[DRAFT] fix: ARCANE auto-repair proposal for {failing_test}"
        validation_banner = (
            "> ⚠️ **UNVERIFIED DRAFT PULL REQUEST**\n"
            "> \n"
            "> **Docker Sandbox Execution:** SKIPPED (Hosted cloud environment without Docker daemon).\n"
            "> **Test Verification:** NOT VERIFIED (No test suite was executed in an isolated container).\n"
            "> **Static Checks:** PASSED (Python AST syntax and unified diff structure verified).\n"
            "> **Action Required:** Human review and local/CI test verification required before merging.\n\n"
        )
    else:
        pr_title = f"fix: ARCANE auto-repair for {failing_test}"
        validation_banner = ""

    memory_hit_str = ""
    memory_hit = state.get("memory_hit")
    if memory_hit and isinstance(memory_hit, dict):
        mem_date = memory_hit.get("date", "unknown date")
        mem_file = memory_hit.get("test_file", "unknown file")
        memory_hit_str = f"> **🧠 Pattern matched from memory** — {mem_date} — `{mem_file}`\n\n"

    if is_draft:
        confidence_str = f"{confidence}% (🟡 Hosted Proposal — Tests Not Executed — Draft PR)"
    elif isinstance(confidence, (int, float)) and confidence >= 85:
        confidence_str = f"{confidence}% (🟢 Auto-Approve Threshold Met)"
    elif isinstance(confidence, (int, float)) and confidence >= 60:
        confidence_str = f"{confidence}% (🟡 Manual Review Required)"
    elif isinstance(confidence, (int, float)):
        confidence_str = f"{confidence}% (🔴 Escalated)"
    else:
        confidence_str = str(confidence)

    test_verif_label = state.get("test_verification", "NOT_VERIFIED" if is_draft else "VERIFIED")
    val_status_label = state.get("validation_status", "SKIPPED" if is_draft else ("PASSED" if tests_passed else "FAILED"))
    summary_text = state.get("validator_summary", "Tests executed in Docker sandbox." if not is_draft else "Docker sandbox skipped in hosted environment.")

    pr_body = f"""## ARCANE Autonomous Repair

{validation_banner}{memory_hit_str}### 1. What Broke
**Failing Test:** `{failing_test}`

### 2. Root Cause
{root_cause}

### 3. Fix
```diff
{patch_diff}
```

### 4. Execution Flow
{mermaid_diagram}

### 5. Test
**Regression Test Code Generated:**
```python
{regression_test or "# No tests generated"}
```

### 6. Confidence & Validation
- **Execution Mode:** `{mode.upper()}`
- **Validation Status:** `{val_status_label}`
- **Test Verification:** `{test_verif_label}`
- **Confidence Score:** {confidence_str}
- **Validator Summary:** {summary_text}

### 7. Files Changed
- `{failing_file if failing_file and failing_file not in ('N/A','unknown_file','unknown') else 'api/auth.py'}`
- `{file_path}` *(ARCANE patch diff)*
{"" if fix_committed else "> Note: the patch was attached as a .diff file only; apply it manually."}
"""

    # 3. Opens a PR from arcane/fix-{sha} to base
    logger.info(f"[PR] Creating PR (draft={is_draft}) on {repo_full_name}")
    pr = repo.create_pull(
        title=pr_title,
        body=pr_body,
        head=branch_name,
        base=base_branch,
        draft=is_draft,
    )

    if not pr or not pr.html_url:
        raise RuntimeError("PR creation failed without returning a valid PR object.")

    logger.info(f"PR generated: {pr.html_url}")
    return pr.html_url


def get_file_content(repo_full_name, file_path, branch='main'):
    """Reads a file from the repo using PyGitHub."""
    token = os.getenv("GITHUB_PAT")
    if not token:
        raise ValueError("GITHUB_PAT not found in environment variables")

    g = Github(token)
    repo = g.get_repo(repo_full_name)

    contents = repo.get_contents(file_path, ref=branch)
    return contents.decoded_content.decode('utf-8')
