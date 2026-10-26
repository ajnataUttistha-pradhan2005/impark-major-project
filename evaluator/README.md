# IMPARK Evaluator: Arize Phoenix & Gemma 4 (e4b) LLM-as-a-Judge

[![Architecture: Decoupled Event-Driven](https://img.shields.io/badge/Architecture-Decoupled_Event--Driven-blue.svg)](#observability-architecture)
[![Judge: gemma4:e4b Local](https://img.shields.io/badge/Judge-gemma4%3Ae4b_(Local_Ollama)-orange.svg)](#the-4-core-evaluation-metrics)
[![Tracing: Arize Phoenix](https://img.shields.io/badge/Tracing-Arize_Phoenix_(Port_6006)-purple.svg)](#arize-phoenix-ui)
[![Idle CPU: 0.0%](https://img.shields.io/badge/Idle_CPU-0.0%25_(OS_Socket_Block)-brightgreen.svg)](#zero-resource-waste-sequential-lifecycle)
[![Storage: PostgreSQL 16](https://img.shields.io/badge/Storage-PostgreSQL_16_(Port_5433)-indigo.svg)](#infrastructure-ports--credentials)

A 100% free, self-hosted observability and evaluation pipeline designed for IMPARK multi-agent workflows. It provides zero hot-path latency telemetry via Redis Streams, sequential evaluation using a local **`gemma4:e4b`** instance as an LLM judge, and long-term trace storage inside PostgreSQL with visualization in **Arize Phoenix**.

---

## Table of Contents
1. [Observability Architecture](#observability-architecture)
2. [The 4 Core Evaluation Metrics](#the-4-core-evaluation-metrics)
3. [Zero-Resource-Waste Sequential Lifecycle](#zero-resource-waste-sequential-lifecycle)
4. [Quickstart (Local & Windows)](#quickstart-local--windows)
5. [Cloud Migration & EC2 Deployment (1-Command Automation)](#cloud-migration--ec2-deployment-1-command-automation)
6. [CLI & Programmatic Usage](#cli--programmatic-usage)
7. [Automated Verification & Test Suites](#automated-verification--test-suites)
8. [Infrastructure Ports & Credentials](#infrastructure-ports--credentials)
9. [Environment Configuration (.env)](#environment-configuration-env)

---

## Observability Architecture

```
                                  +---------------------------------------+
                                  |  Local LLM Server (Ollama / vLLM)     |
                                  |  Model: 'gemma4:e4b'                  |
                                  |  Endpoint: http://localhost:11434/v1  |
                                  +---------------------------------------+
                                             ^                 ^
                         (Step 1: Main Task) |                 | (Step 3: Sequential Judge)
                                             |                 |
[User Request / Agent Action] ---------------+                 |
              │                                                |
              ▼                                                |
[LangChain DeepAgents Orchestrator]                            |
   - Intercepts graph retrieval step                           |
   - Tracks graph_retrieval_time (time.perf_counter)          |
   - Dispatches tool calling with ground truth expected tool   |
   - Captures OpenTelemetry span context                       |
              │                                                |
              ▼ (< 1ms non-blocking publish)                  |
[Redis Streams Queue ('phoenix-agent-traces')]                 |
   - Asynchronously enqueues trace payload                     |
   - Main Agent goes to SLEEP (Task complete, VRAM freed)      |
              │                                                |
              ▼ (Blocking XREAD BLOCK 0 / socket sleep)        |
[Idle-Aware Sequential Judge Worker] --------------------------+
   - Sits at 0.0% CPU blocked on Redis network socket
   - Wakes up immediately upon new trace stream entry
   - Sequentially calls gemma4:e4b as Judge:
       * Evaluates Groundedness & Hallucination Rate (strict JSON)
       * Computes Tool Selection Accuracy (1.0 or 0.0)
       * Extracts real graph_retrieval_time from span metadata
   - Logs evaluations permanently to Phoenix Postgres backend
     using px.log_evaluations / SpanEvaluations
   - Forwards span via OTLP to Phoenix UI (http://localhost:6006)
   - Immediately returns to IDLE / SLEEP (Redis XREAD BLOCK)
              │
              ▼
[Arize Phoenix & PostgreSQL Storage Backend]
   - Phoenix UI at http://localhost:6006
   - PostgreSQL storing traces, spans, and evaluations permanently
```

---

## The 4 Core Evaluation Metrics

| Metric | Measurement Mechanism | Formula / Behavior |
| :--- | :--- | :--- |
| **`graph_retrieval_time`** | Python `time.perf_counter()` wrapped directly around live GraphAgent execution | $(t_{\text{end}} - t_{\text{start}}) \times 1000 \text{ ms}$ (Microsecond precision) |
| **`tool_selection_accuracy`** | Deterministic comparison of orchestrator's selected tool against expected ground truth | $1.0 \text{ if selected == expected else } 0.0$ |
| **`groundedness`** | Evaluated sequentially after generation by prompting `gemma4:e4b` under a strict JSON format constraint | $\text{Score } \in [0.0, 1.0]$ based on retrieved evidence support |
| **`hallucination_rate`** | Mathematical inverse of groundedness emitted by the judge | $1.0 - \text{Groundedness} \in [0.0, 1.0]$ |

---

## Zero-Resource-Waste Sequential Lifecycle

To run seamlessly on consumer hardware with limited RAM/VRAM:
1. **Single Model Instance**: We use a single local model instance (`gemma4:e4b` on Ollama).
2. **No Parallel Execution Collisions**: The main agent task executes and finishes completely first. Once the response is streamed to the user, the agent enters sleep state.
3. **Sequential Judge Wake-Up**: The exact same model instance wakes up sequentially to act as the Evaluation Judge.
4. **0.0% Idle CPU Utilization**: The judge worker uses blocking Redis reads (`XREAD BLOCK 0`). When no queries are active, the thread enters OS kernel sleep with zero CPU/GPU overhead.

---

## Quickstart (Local & Windows)

### Option 1: 1-Click PowerShell Script (Recommended)

```powershell
cd evaluator

# Start infrastructure and run the continuous idle-aware worker:
.\deploy_windows.ps1

# Or run a single real agent query evaluation directly:
.\deploy_windows.ps1 -Query "What are the active phytochemicals of Withania somnifera?"

# Or run the self-test verification demo:
.\deploy_windows.ps1 -Demo
```

This script automatically:
1. Verifies Docker Desktop is running and launches `eval-redis`, `eval-postgres`, and `eval-phoenix`.
2. Automatically creates the `phoenix` database and `agent_evaluations` table inside PostgreSQL.
3. Checks if local Ollama daemon is running at `http://localhost:11434` with model `gemma4:e4b`.
4. Starts the **Continuous Idle-Aware Evaluation Judge Worker** (sitting in kernel socket read at 0.0% CPU until real agent traces arrive).
5. Exposes the Arize Phoenix UI at **[http://localhost:6006](http://localhost:6006)**.

---

### Option 2: Manual Step-by-Step

#### 1. Start Infrastructure Containers
```powershell
cd evaluator
docker compose up -d
```
*Spins up Redis 7 (port 6379), PostgreSQL 16 (host port 5433), and Arize Phoenix (port 6006).*

> [!TIP]
> **Fix for `database "phoenix" does not exist`**:
> If your Postgres container had an existing volume from an earlier setup, run:
> ```powershell
> docker exec -i eval-postgres psql -U postgres -c "CREATE DATABASE phoenix;"
> ```
> The Python pipeline and `deploy_windows.ps1` also automatically detect and self-heal missing databases on launch.

#### 2. Install Python Dependencies
```powershell
pip install -r requirements.txt
```

#### 3. Start Ollama and Pull the Judge Model
```powershell
ollama serve
ollama pull gemma4:e4b
```

#### 4. Run the Idle-Aware Judge Worker Daemon
```powershell
python phoenix_pipeline.py --worker
```
*The judge sits completely idle (0.0% CPU) until an agent turn executes, evaluates it sequentially, commits to Phoenix & PostgreSQL, and returns to sleep.*

#### 5. Open Arize Phoenix UI
Navigate to **[http://localhost:6006](http://localhost:6006)** to inspect all spans, traces, and LLM evaluation grades in real time.

---

## Cloud Migration & EC2 Deployment (1-Command Automation)

To deploy to an AWS EC2 instance (Ubuntu 22.04 / 24.04 or Amazon Linux 2023 on `t3.medium`):

### 1. Configure Inbound Rules in AWS Security Group
* Port `6006` (Arize Phoenix UI)
* Port `22` (SSH)

### 2. Run the 1-Command Cloud Deployment Script
```bash
git clone <your-repository-url>
cd impark-major-project/evaluator
chmod +x deploy_ec2.sh
./deploy_ec2.sh
```

---

## CLI & Programmatic Usage

### CLI Commands

```powershell
# 1. Run continuous idle-aware background worker (0.0% CPU socket sleep)
python phoenix_pipeline.py --worker

# 2. Run evaluation on a real live agent turn for a specific query & plant
python phoenix_pipeline.py --query "What are the active phytochemicals of Withania somnifera?" --plant withania_somnifera --expected-tool query_knowledge_graph

# 3. Run end-to-end self-test verification demo
python phoenix_pipeline.py --demo
```

### Inspecting Live Telemetry & Persisted Records

```powershell
# Inspect Redis Stream for queued agent traces:
docker exec -it eval-redis redis-cli XRANGE phoenix-agent-traces - + COUNT 5
docker exec -it eval-redis redis-cli XRANGE my_stream - + COUNT 5

# Inspect evaluations committed to PostgreSQL:
docker exec -it eval-postgres psql -U postgres -d phoenix -c "SELECT id, trace_id, groundedness, hallucination_rate, graph_retrieval_time_ms, tool_selection_accuracy, created_at FROM agent_evaluations ORDER BY id DESC LIMIT 5;"

# Open Arize Phoenix Observability Dashboard:
# http://localhost:6006
```

### Programmatic Python Usage

```python
from evaluator.phoenix_pipeline import (
    execute_agent_pipeline,
    IdleAwareEvaluationJudge,
    get_redis_connection,
    get_postgres_connection,
)

# Execute agent turn & queue trace
agent_result = execute_agent_pipeline(
    user_query="What are the indications of Withania somnifera?",
    expected_tool="query_knowledge_graph",
)

# Awaken sequential judge worker to evaluate
judge = IdleAwareEvaluationJudge(
    redis_client=get_redis_connection(),
    postgres_conn=get_postgres_connection(),
)
eval_result = judge.evaluate_span({
    "trace_id": agent_result["trace_id"],
    "span_id": agent_result["span_id"],
    "attributes": {
        "input.value": "What are the indications of Withania somnifera?",
        "output.value": agent_result["output"],
        "retrieved_context": agent_result["context"],
        "graph_retrieval_time_ms": agent_result["graph_retrieval_time_ms"],
        "tool_selection_accuracy": agent_result["tool_selection_accuracy"],
    },
})

print(f"Groundedness: {eval_result['groundedness']}")
print(f"Hallucination Rate: {eval_result['hallucination_rate']}")
print(f"Retrieval Time: {eval_result['graph_retrieval_time']} ms")
```

---

## Automated Verification & Test Suites

Run the automated test suite anytime to verify all 4 metrics, the Redis non-blocking exporter, and worker lifecycle:

```powershell
pytest test_phoenix_pipeline.py -v
```

### Test Suite Coverage:
* `test_metric_1_graph_retrieval_time`: Proves live GraphAgent retrieval latency is measured (> 0ms).
* `test_metric_2_tool_selection_accuracy`: Proves binary 1.0/0.0 evaluation against expected tool ground truth.
* `test_metrics_3_and_4_groundedness_and_hallucination_rate`: Proves JSON judge prompt adherence and mathematical inverse consistency ($G + H = 1.0$).
* `test_redis_stream_span_exporter_queue`: Proves non-blocking OpenTelemetry span queueing via Redis Streams.
* `test_idle_aware_worker_single_item_lifecycle`: Proves Start -> Evaluate -> Commit -> Sleep sequential lifecycle.

---

## Infrastructure Ports & Credentials

| Service | Host Port | Internal Port | URL / Access | Description |
| :--- | :--- | :--- | :--- | :--- |
| **Arize Phoenix UI** | `6006` | `6006` | <http://localhost:6006> | Web UI for tracing, spans, and LLM evaluations |
| **Arize Phoenix OTLP** | `4317` | `4317` | `http://localhost:4317` | OTLP gRPC telemetry endpoint |
| **PostgreSQL** | `5433` (or `EVAL_POSTGRES_PORT`) | `5432` | `localhost:5433` (db: `phoenix`, user: `postgres`, password: `password`) | Persistent storage for Arize Phoenix |
| **Redis** | `6379` | `6379` | `localhost:6379` (stream: `phoenix-agent-traces`) | AOF Persistent Broker for Non-Blocking Trace Queuing |

---

## Environment Configuration (.env)

Copy `.env.example` to `.env` to customize settings:

```ini
# Local LLM Server (Ollama)
OPENAI_BASE_URL=http://localhost:11434/v1
OLLAMA_BASE_URL=http://localhost:11434
OPENAI_API_KEY=ollama
AGENT_MODEL=gemma4:e4b
EVAL_MODEL=gemma4:e4b
EVAL_LLM_TIMEOUT=15.0

# Redis Streams Configuration
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_STREAM=phoenix-agent-traces

# PostgreSQL Unified Storage Configuration
EVAL_POSTGRES_PORT=5433
POSTGRES_HOST=localhost
POSTGRES_PORT=5433
POSTGRES_USER=postgres
POSTGRES_PASSWORD=password
POSTGRES_DB=phoenix

# Arize Phoenix Configuration
PHOENIX_ENDPOINT=http://localhost:6006
PHOENIX_COLLECTOR_ENDPOINT=http://localhost:6006/v1/traces
PHOENIX_PROJECT_NAME=impark-deepagents
```
