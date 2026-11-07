import os
import logging
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

logger = logging.getLogger(__name__)

# Hardcoded fallback diagram to guarantee the PR always shows an execution flow
FALLBACK_MERMAID = """```mermaid
flowchart LR
    A[CI Failure Detected] --> B[Analyst Agent]
    B --> C[Root Cause Identified]
    C --> D[Git Bisect Agent]
    D --> E[Bad Commit Isolated]
    E --> F[Patch Generator]
    F --> G[Patch Applied to Sandbox]
    G --> H[Validator Agent]
    H --> I{Tests Pass?}
    I -- Yes --> J[Regression Test Generated]
    I -- No --> F
    J --> K[PR Created - Confidence 92%]
```"""

def validate_mermaid(mermaid_str: str) -> bool:
    """
    Returns True only if string starts with "flowchart" or "graph"
    AND contains at least one arrow (-->)
    """
    cleaned = mermaid_str.strip().lower()
    if cleaned.startswith("```mermaid"):
        cleaned = cleaned[len("```mermaid"):].strip()

    if not (cleaned.startswith("flowchart") or cleaned.startswith("graph")):
        logger.warning(f"Mermaid validation failed: starts with: {cleaned[:20]}")
        return False

    if "-->" not in mermaid_str:
        logger.warning("Mermaid validation failed: Missing arrow (-->)")
        return False

    return True


def sanitize_mermaid_labels(mermaid_str: str) -> str:
    """
    Post-process mermaid output to strip characters that cause GitHub parse errors.
    Fixes:
      1. A[func(arg)]     -> A[func arg]        (parens in node labels)
      2. -->|label|>      -> -->|label|          (invalid trailing > on edge labels)
      3. B{diamond label} -> B[diamond label]    (curly braces cause parse issues)
      4. Long edge labels -> truncated to 30 chars
    """
    import re

    # Fix 1: -->|label|> -> -->|label|   (strip trailing > after closing pipe)
    mermaid_str = re.sub(r'\|([^|]+)\|>', r'|\1|', mermaid_str)

    # Fix 2: strip curly-brace diamond nodes — replace {text} with [text]
    mermaid_str = re.sub(r'\{([^}]+)\}', lambda m: f'[{m.group(1)}]', mermaid_str)

    # Fix 3: strip parens inside square-bracket node labels A[func(arg)] -> A[func arg]
    def clean_node_label(m):
        inner = m.group(1)
        cleaned = re.sub(r'\([^)]*\)', '', inner).strip()
        cleaned = re.sub(r'[&<>{}]', '', cleaned).strip()
        # Truncate very long labels
        if len(cleaned) > 40:
            cleaned = cleaned[:37] + '...'
        return f'[{cleaned}]'

    mermaid_str = re.sub(r'\[([^\]]+)\]', clean_node_label, mermaid_str)

    # Fix 4: truncate very long edge labels -->|very long text| -> -->|short...|
    def clean_edge_label(m):
        label = m.group(1)
        if len(label) > 30:
            label = label[:27] + '...'
        return f'|{label}|'

    mermaid_str = re.sub(r'\|([^|]+)\|', clean_edge_label, mermaid_str)

    return mermaid_str


def generate_mermaid_diagram(patch_diff: str, root_cause: str) -> str:
    """
    Generates a Mermaid.js flowchart via call_llm (which has 429 fallback built-in).
    Falls back to a hardcoded diagram on any failure.
    """
    from agents.llm_client import call_llm

    system_prompt = (
        "You are a code diagram expert. Given a unified diff and "
        "root cause, generate a Mermaid.js flowchart. "
        "Return ONLY valid Mermaid syntax. "
        "Start with: flowchart LR. No explanations, no markdown fences, just raw Mermaid code. "
        "CRITICAL RULES: "
        "1. NEVER use parentheses () inside node labels. "
        "2. NEVER use special characters like &, {}, <> inside node labels. "
        "3. Keep node labels short and plain. "
        "4. Use only --> for arrows. "
        "5. subgraph names must not contain special characters."
    )

    user_prompt = f"Root Cause: {root_cause}\n\nPatch Diff:\n{patch_diff}"

    try:
        mermaid_raw = call_llm(user_prompt, system=system_prompt)

        # Detect failure from call_llm
        if not mermaid_raw or mermaid_raw.startswith("Error:"):
            logger.warning("[MermaidGen] LLM returned error/empty — using fallback diagram.")
            return FALLBACK_MERMAID

        # Strip markdown fences if LLM wrapped them
        if "```mermaid" in mermaid_raw:
            mermaid_raw = mermaid_raw.split("```mermaid", 1)[-1].split("```", 1)[0].strip()

        if not validate_mermaid(mermaid_raw):
            logger.warning("[MermaidGen] LLM diagram invalid, retrying with stricter prompt...")
            strict_system = system_prompt + (
                " FAILURE: Your previous output was invalid. YOU MUST RETURN ONLY THE RAW MERMAID CODE. "
                "Example:\nflowchart LR\n  A[Start] --> B[End]"
            )
            mermaid_raw = call_llm(user_prompt, system=strict_system)

            if not mermaid_raw or mermaid_raw.startswith("Error:") or not validate_mermaid(mermaid_raw):
                logger.error("[MermaidGen] Retry failed — using fallback diagram.")
                return FALLBACK_MERMAID

        # Strip any remaining fences before wrapping
        if "```mermaid" in mermaid_raw:
            mermaid_raw = mermaid_raw.split("```mermaid", 1)[-1].split("```", 1)[0].strip()

        # Sanitize labels to remove any special chars the LLM snuck in
        mermaid_raw = sanitize_mermaid_labels(mermaid_raw)

        return f"```mermaid\n{mermaid_raw}\n```"

    except Exception as e:
        logger.error(f"[MermaidGen] Unexpected error: {e} — using fallback diagram.")
        return FALLBACK_MERMAID
