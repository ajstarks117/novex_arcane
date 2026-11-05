import subprocess
import os
import uuid
import time
from typing import Optional, Dict, Any

def run_sandbox(repo_url: str, commit_sha: str, patch_diff: Optional[str] = None) -> Dict[str, Any]:
    """
    Boots a Docker container, clones a repository inside it, applies an optional patch, and runs pytest.
    """
    container_name = f"arcane-{uuid.uuid4().hex[:8]}"
    print(f"Starting container: {container_name}")
    
    try:
        # 1. Boot the container
        # We run it in the background and keep it alive with 'tail -f /dev/null' or 'sleep infinity'
        subprocess.run(
            ["docker", "run", "-d", "--name", container_name, "arcane-sandbox", "sleep", "infinity"],
            check=True,
            capture_output=True,
            text=True
        )

        # Helper to run commands inside the container
        def exec_in_container(cmd, input_str=None, timeout=None):
            return subprocess.run(
                ["docker", "exec", "-i", container_name] + cmd,
                input=input_str,
                capture_output=True,
                text=True,
                timeout=timeout
            )

        # 2. Clone the repository inside the container's /sandbox
        clone_res = exec_in_container(["git", "clone", repo_url, "."])
        if clone_res.returncode != 0:
            return {"passed": False, "output": f"Clone failed: {clone_res.stderr}", "exit_code": clone_res.returncode}

        # 3. Checkout the specific commit SHA
        checkout_res = exec_in_container(["git", "checkout", commit_sha])
        if checkout_res.returncode != 0:
            return {"passed": False, "output": f"Checkout failed: {checkout_res.stderr}", "exit_code": checkout_res.returncode}

        # 4. Apply patch if provided
        if patch_diff:
            patch_res = exec_in_container(["patch", "-p1"], input_str=patch_diff)
            if patch_res.returncode != 0:
                return {"passed": False, "output": f"Patch failed: {patch_res.stderr}", "exit_code": patch_res.returncode}

        # 5. Run pytest with a 120-second timeout
        try:
            pytest_res = exec_in_container(["env", "PYTHONPATH=.", "pytest", "-v"], timeout=120)
            return {
                "passed": pytest_res.returncode == 0,
                "output": pytest_res.stdout + pytest_res.stderr,
                "exit_code": pytest_res.returncode
            }
        except subprocess.TimeoutExpired:
            return {"passed": False, "output": "TIMEOUT", "exit_code": -1}

    except subprocess.CalledProcessError as e:
        return {
            "passed": False,
            "output": f"Docker operation failed: {e.stderr}",
            "exit_code": e.returncode
        }
    except Exception as e:
        return {
            "passed": False,
            "output": f"An unexpected error occurred: {str(e)}",
            "exit_code": 1
        }
    finally:
        # 6. Always remove the container
        subprocess.run(["docker", "rm", "-f", container_name], capture_output=True)

if __name__ == "__main__":
    pass

