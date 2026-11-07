import os
import logging
from github import Github
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

from agents.mermaid_generator import generate_mermaid_diagram

def create_pr(state: dict) -> str:
    """
    Creates a new branch from main, commits the patch diff,
    and opens a PR with the full 7-section format.
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
    
    g = Github(token)
    repo = g.get_repo(repo_full_name)
    
    branch_name = f"arcane/fix-{commit_sha[:7]}"
    base_branch = "main"
    
    # 1. Create a new branch from main
    base_ref = repo.get_git_ref(f"heads/{base_branch}")
    try:
        repo.create_git_ref(ref=f"refs/heads/{branch_name}", sha=base_ref.object.sha)
    except Exception as e:
        logger.warning(f"Branch creation exception (might already exist): {e}")
        
    # 2. Commit the patch_diff content to the file on this branch
    file_path = f"arcane_patch_{commit_sha[:7]}.diff"
    commit_msg = f"fix: ARCANE auto-repair code patch for {failing_test}"
    
    try:
        contents = repo.get_contents(file_path, ref=branch_name)
        repo.update_file(contents.path, commit_msg, patch_diff, contents.sha, branch=branch_name)
    except Exception:
        repo.create_file(file_path, commit_msg, patch_diff, branch=branch_name)
        
    # Generate mermaid diagram
    logger.info("Generating Mermaid diagram...")
    mermaid_diagram = generate_mermaid_diagram(patch_diff, root_cause)

    # Compile the 7-section PR body
    pr_title = f"fix: ARCANE auto-repair for {failing_test}"
    
    memory_hit_str = ""
    if "date" in state and "test_file" in state:
        memory_hit_str = f"> **🧠 Pattern matched from memory** — {state['date']} — `{state['test_file']}`\n\n"
    
    pr_body = f"""## ARCANE Autonomous Repair

{memory_hit_str}### 1. What Broke
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

### 6. Confidence
- **Score:** {confidence}%
- **Validator Passed:** {tests_passed}

### 7. Files Changed
- `{failing_file}`
"""

    # 3. Opens a PR from arcane/fix-{sha} to main
    pr = repo.create_pull(
        title=pr_title,
        body=pr_body,
        head=branch_name,
        base=base_branch
    )
    
    if not pr or not pr.html_url:
        raise RuntimeError("PR creation failed without returning a valid PR object.")
        
    logger.info(f"PR generated: {pr.html_url}")
    return pr.html_url

def get_file_content(repo_full_name, file_path, branch='main'):
    """
    Reads a file from the repo using PyGitHub.
    """
    token = os.getenv("GITHUB_PAT")
    if not token:
        raise ValueError("GITHUB_PAT not found in environment variables")
        
    g = Github(token)
    repo = g.get_repo(repo_full_name)
    
    contents = repo.get_contents(file_path, ref=branch)
    return contents.decoded_content.decode('utf-8')
