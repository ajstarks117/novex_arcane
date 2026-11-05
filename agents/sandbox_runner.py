import subprocess
import os
import tempfile
import shutil
from typing import Optional, Dict, Any

def run_sandbox(repo_url: str, commit_sha: str, patch_diff: Optional[str] = None) -> Dict[str, Any]:
    """
    Clones a repository, applies an optional patch, and runs pytest.
    """
    # Use a temporary directory for cloning to ensure cleanup
    with tempfile.TemporaryDirectory(dir="/sandbox") as tmp_dir:
        try:
            # 1. Clone the repository
            # We clone into the temporary directory
            subprocess.run(
                ["git", "clone", repo_url, "."],
                cwd=tmp_dir,
                check=True,
                capture_output=True,
                text=True
            )

            # 2. Checkout the specific commit SHA
            subprocess.run(
                ["git", "checkout", commit_sha],
                cwd=tmp_dir,
                check=True,
                capture_output=True,
                text=True
            )

            # 3. Apply patch if provided
            if patch_diff:
                patch_process = subprocess.run(
                    ["patch", "-p1"],
                    input=patch_diff,
                    cwd=tmp_dir,
                    capture_output=True,
                    text=True
                )
                if patch_process.returncode != 0:
                    return {
                        "passed": False,
                        "output": f"Patch application failed:\n{patch_process.stderr}",
                        "exit_code": patch_process.returncode
                    }

            # 4. Run pytest with a 120-second timeout
            try:
                pytest_process = subprocess.run(
                    ["pytest"],
                    cwd=tmp_dir,
                    capture_output=True,
                    text=True,
                    timeout=120
                )
                
                return {
                    "passed": pytest_process.returncode == 0,
                    "output": pytest_process.stdout + pytest_process.stderr,
                    "exit_code": pytest_process.returncode
                }

            except subprocess.TimeoutExpired:
                return {
                    "passed": False,
                    "output": "TIMEOUT",
                    "exit_code": -1
                }

        except subprocess.CalledProcessError as e:
            return {
                "passed": False,
                "output": f"Git operation failed:\n{e.stderr}",
                "exit_code": e.returncode
            }
        except Exception as e:
            return {
                "passed": False,
                "output": f"An unexpected error occurred: {str(e)}",
                "exit_code": 1
            }

if __name__ == "__main__":
    # Example usage (can be modified or imported)
    # result = run_sandbox("https://github.com/example/repo.git", "main")
    # print(result)
    pass
