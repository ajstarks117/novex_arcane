# ARCANE — Autonomous Repair & Conflict-Aware Node Engine 🔮

**ARCANE** is a state-of-the-art, fully autonomous CI/CD failure repair pipeline. Built entirely on **LangGraph** and powered by **Google Gemini**, ARCANE detects test failures from GitHub webhooks, isolates the breaking commit, generates an intelligent patch, validates it in an isolated Docker sandbox, and automatically opens a robust Pull Request with a regression test. 

It is designed to give engineering teams back their time by transforming **"Tests Failed"** into **"Fix Ready to Merge"** in under 90 seconds.

---

## 🚀 Key Features

* **Event-Driven Architecture**: Native FastAPI webhook receiver listens in real-time to GitHub commit pushes and workflow runs.
* **LangGraph Orchestration**: Uses a customized state machine with looping capabilities to orchestrate 8 distinct intelligent agents.
* **Autonomous Docker Sandbox**: Uses `docker exec` to dynamically spawn secure environments, apply code patches natively via unified diffs, and validate them with `pytest` within seconds.
* **Intelligent Git Bisecting**: Autonomously steps backward through commit history in the sandbox to isolate the exact commit that introduced the bug.
* **ChromaDB Memory Fast-Forward**: Caches successful patches globally. If the same error signature is detected again, ARCANE bypasses LLM generation entirely and applies the fix via a sub-second "fast-forward" path.
* **Rich GitHub Integrations**: Automatically opens Pull Requests featuring custom Mermaid.js execution flowcharts, syntax-highlighted regression tests, and confidence-score driven auto-approval badging.

---

## 🧠 The Agent Arsenal

ARCANE utilizes a multi-agent architectural design to separate concerns and ensure extremely high code-quality throughput:

1. **Analyst Agent**: Ingests raw CI failure logs and extracts the precise failing test, file, and root-cause mechanism.
2. **Bisect Agent**: Replays the repository history inside a Docker container to find the exact SHA that broke the build.
3. **Patch Generator**: Interfaces with Google Gemini to read the failing test context and generate a drop-in replacement unified diff.
4. **Validator Agent**: Applies the newly generated patch to the repository in an isolated sandbox and re-runs the entire test suite to ensure cascade failures have not occurred.
5. **Conflict Resolver**: Integrates AST-aware conflict capabilities for highly complex branch merges.
6. **Regression Test Generator**: Synthesizes a dedicated `pytest` function designed specifically to trap the original root cause, preventing the bug from ever returning.
7. **PR Agent**: Compiles the execution flow into an interactive Mermaid diagram and pushes a highly stylized 7-section Pull Request back to the developer.

---

## 🏗️ System Architecture

1. **Trigger**: Developer pushes code -> GitHub Action fails -> Webhook pings FastAPI.
2. **State Machine**: LangGraph initializes `ArcaneState`.
3. **Memory Check**: `ChromaDB` queried for historical matches to enable fast-forwarding.
4. **Bisect**: Docker boots, `git bisect` runs to find the breaking commit.
5. **Patch**: Gemini synthesizes a diff.
6. **Validate**: Docker applies patch, `pytest` executes.
    * *Failure*: Feeds cascade report back to Patch Generator (Loop limit: 3).
    * *Success*: Proceeds to test generation.
7. **Write Tests**: Gemini writes `test_regression.py`.
8. **Finalize**: Mermaid diagram drawn, JSON payload pushed to GitHub REST API.

---

## 🛠️ Setup & Installation

### Environment Requirements
* Python 3.10+
* Docker Desktop (Engine must be running)
* Ngrok or Pinggy (for webhook tunneling)

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure Environment variables
Create a `.env` file in the root directory:
```ini
GITHUB_PAT=your_github_personal_access_token
GEMINI_API_KEY=your_google_api_key
CHROMADB_PATH=./chroma_data
```

### 3. Build the Sandbox
Build the isolated testing environment container natively:
```bash
docker build -t arcane-sandbox -f Dockerfile.sandbox .
```

### 4. Start the Pipeline
Start the FastAPI server:
```bash
uvicorn api.main:app --reload
```

Expose the local server to the public internet using Pinggy:
```bash
ssh -p 443 -R0:127.0.0.1:8000 qr@a.pinggy.io
```

*Place the resulting URL into your GitHub Repository Webhook settings.*

---

## 💻 Tech Stack
- **AI Core:** Google Gemini 2.5 Flash, LangGraph
- **Backend:** FastAPI, Python, Uvicorn
- **Vector DB:** ChromaDB
- **Infrastructure:** Docker, Pytest, Git
- **Integrations:** PyGithub, Mermaid.js
