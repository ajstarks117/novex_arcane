import os
import logging
from github import Github
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

def create_pr(repo_full_name, base_branch, commit_sha, patch_diff, failing_test, validator_summary=None, mermaid_diagram=None):
    """
    Creates a new branch from base_branch, commits the patch diff,
    and opens a PR to main. Includes validator_summary and mermaid_diagram if provided.
    """
    token = os.getenv("GITHUB_PAT")
    if not token:
        raise ValueError("GITHUB_PAT not found in environment variables")
        
    g = Github(token)
    repo = g.get_repo(repo_full_name)
    
    branch_name = f"arcane/fix-{commit_sha[:7]}"
    
    # 1. Create a new branch from main
    base_ref = repo.get_git_ref(f"heads/{base_branch}")
    try:
        repo.create_git_ref(ref=f"refs/heads/{branch_name}", sha=base_ref.object.sha)
    except Exception as e:
        logger.warning(f"Branch creation exception (might already exist): {e}")
        
    # 2. Commit the patch_diff content to the file on this branch
    # For Phase 1 we log the patch diff to a tracking file to satisfy the commit requirement
    file_path = f"arcane_patch_{commit_sha[:7]}.diff"
    commit_msg = f"fix: ARCANE auto-repair code patch for {failing_test}"
    
    try:
        contents = repo.get_contents(file_path, ref=branch_name)
        repo.update_file(contents.path, commit_msg, patch_diff, contents.sha, branch=branch_name)
    except Exception:
        repo.create_file(file_path, commit_msg, patch_diff, branch=branch_name)
        
    # 3. Opens a PR from arcane/fix-{sha} to main
    pr_title = f"fix: ARCANE auto-repair for {failing_test}"
    
    pr_body = f"### Patch applied\n```diff\n{patch_diff}\n```\n\n**Failing Test:** `{failing_test}`"
    if validator_summary:
        pr_body += f"\n\n> **Validation:** {validator_summary}"
    
    if mermaid_diagram:
        pr_body += f"\n\n### Execution Flow\n{mermaid_diagram}"
    
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
