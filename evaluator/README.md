# IMPARK Multi-Agent Evaluator & Observability Pipeline

[![Architecture: Decoupled Event-Driven](https://img.shields.io/badge/Architecture-Decoupled_Event--Driven-blue.svg)](#observability-architecture-dual-stack-design)
[![Inference: CPU Only](https://img.shields.io/badge/Inference-CPU--Only_(~220MB_RAM)-success.svg)](#stack-2-grafana--cpu-semantic-evaluator-redis_evaluatorpy)
[![Judge: gemma3:4b Local](https://img.shields.io/badge/Judge-gemma3%3A4b_(Local_Ollama)-orange.svg)](#stack-1-arize-phoenix--gemma34b-llm-as-a-judge-phoenix_pipelinepy)
[![Idle CPU: 0.0%](https://img.shields.io/badge/Idle_CPU-0.0%25_(OS_Socket_Block)-brightgreen.svg)](#core-design-constraints--architectural-highlights)
[![Storage: PostgreSQL 16 JSONB](https://img.shields.io/badge/Storage-PostgreSQL_16_JSONB_%2B_GIN-indigo.svg)](#infrastructure-ports--default-credentials)

A 100% self-hosted, production-grade observability and evaluation pipeline designed for LangGraph and DeepAgents multi-agent workflows. It provides real-time telemetry, zero hot-path latency, automated semantic grading, Arize Phoenix trace routing, and executive Grafana dashboards.

---

## Table of Contents
1. [Core Design Constraints & Architectural Highlights](#core-design-constraints--architectural-highlights)
2. [Repository & File Structure](#repository--file-structure)
3. [Observability Architecture: Dual-Stack Design](#observability-architecture-dual-stack-design)
4. [Stack 1: Arize Phoenix + Gemma3:4b LLM-as-a-Judge (`phoenix_pipeline.py`)](#stack-1-arize-phoenix--gemma34b-llm-as-a-judge-phoenix_pipelinepy)
   - [The 4 Core Phoenix Metrics](#the-4-core-phoenix-metrics)
   - [Functions & Code API Reference](#functions--code-api-reference-phoenix_pipelinepy)
   - [CLI Usage & Execution Commands](#cli-usage--execution-commands-phoenix_pipelinepy)
5. [Stack 2: Grafana + CPU Semantic Evaluator (`redis_evaluator.py`)](#stack-2-grafana--cpu-semantic-evaluator-redis_evaluatorpy)
   - [The 6 Core CPU Metrics](#the-6-core-cpu-metrics)
   - [Functions & Code API Reference](#functions--code-api-reference-redis_evaluatorpy)
   - [Grafana Dashboard & Pre-Configured Provisioning](#grafana-dashboard--pre-configured-provisioning)
6. [Quickstart: Local & Docker Deployment](#quickstart-local--docker-deployment)
7. [Cloud Migration & EC2 Deployment (1-Command Automation)](#cloud-migration--ec2-deployment-1-command-automation)
8. [Live Agentic Orchestrator Telemetry (Zero Hardcoding)](#live-agentic-orchestrator-telemetry-zero-hardcoding)
9. [Automated Verification & Test Suites](#automated-verification--test-suites)
10. [Infrastructure Ports, Credentials & Environment Variables](#infrastructure-ports-credentials--environment-variables)

---

## Core Design Constraints & Architectural Highlights

| Constraint | Architectural Decision | Implementation Impact |
| :--- | :--- | :--- |
| **Zero Hot-Path Latency** | Non-blocking Redis Stream (`XADD`) | User chat experiences **< 1ms overhead**; telemetry is decoupled from response generation. If Redis is down, circuit breakers skip network calls with 0ms delay. |
| **Sequential Resource Conservation** | Single Shared `gemma3:4b` Instance | The main agent generates an answer and goes to sleep; the exact same model instance wakes up sequentially as an evaluation judge. Zero parallel thread GPU/VRAM collisions. |
| **Local CPU-Only NLP Grading** | Hybrid Bi-Encoder + NLI Cross-Encoder | `all-MiniLM-L6-v2` (embeddings, ~80MB) + `cross-encoder/nli-deberta-v3-small` (NLI, ~140MB). Operates in **~45ms on CPU** with **zero external API costs**. |
| **Idle State Efficiency** | OS Socket Network Sleep (`XREAD BLOCK 0`) | When no queries or tool invocations are running, the worker daemon enters interruptible kernel socket sleep (**0.0% idle CPU utilization**). |
| **Schema Agility & Durability** | PostgreSQL 16 `JSONB` + GIN Index | Raw trace payloads and relational evaluation metrics persist permanently in PostgreSQL, backed by Arize Phoenix storage. |
| **Aggregated Tool Logging** | Single Consolidated End-of-Turn Payload | Tool invocations are captured and aggregated per turn. Telemetry is streamed to Redis **only when an action/tool was performed**, preventing stream flooding. |

---

## Repository & File Structure

```
impark-major-project/evaluator/
├── docker-compose.yml              # Multi-container orchestration (Redis 7, Postgres 16, Grafana, Arize Phoenix)
├── Dockerfile                      # CPU-optimized container with pre-cached models (~220MB RAM)
├── requirements.txt                # Lean Python dependencies for host & container execution
├── local_tracer.py                 # BaseCallbackHandler intercepting LangChain/LangGraph events (<1ms publish)
├── redis_evaluator.py              # Blocking CPU evaluator daemon (XREAD BLOCK 0, math metrics, Postgres commit)
├── test_pipeline.py                # End-to-end simulation suite verifying Flow 1 (Live) & Flow 2 (Benchmark)
├── phoenix_pipeline.py             # OpenTelemetry + Arize Phoenix + Ollama/gemma3:4b LLM-as-a-Judge pipeline
├── test_phoenix_pipeline.py        # Verification suite for all 4 Phoenix metrics, Redis queue & Idle Worker
├── init-db.sql                     # PostgreSQL schema initialization for both eval_db and phoenix databases
├── deploy_ec2.sh                   # Production cloud deployment automation script for AWS EC2 Linux
├── deploy_windows.ps1              # Windows local PowerShell launcher & verification script
├── README.md                       # Comprehensive operational & architecture guide
└── grafana/
    ├── provisioning/
    │   ├── datasources/
    │   │   └── datasource.yml     # Auto-registers PostgreSQL (eval_db) datasource at Grafana boot
    │   └── dashboards/
    │       └── dashboards.yml     # Auto-loads dashboard provider from local JSON
    └── dashboards/
        └── agent_evaluation_dashboard.json # Production dashboard: 5 KPI Gauges, Latency, Trends & Traces
```

---

## Observability Architecture: Dual-Stack Design

The IMPARK evaluation system provides two complementary observability pipelines feeding from the same live agent telemetry:

```
                            [User Request / Agent Action]
                                          │
                                          ▼
                         [LangChain DeepAgents Orchestrator]
                     (GraphAgent, TextAgent, ImageAgent Execution)
                                          │
                                          ▼
                      [LocalRedisTracer Callback Aggregator]
                       (Captures Monotonic Latency & Claims)
                                          │
                   ┌──────────────────────┴──────────────────────┐
                   │                                             │
                   ▼ (Stream: phoenix-agent-traces)              ▼ (Stream: agent-logs)
        [Phoenix Pipeline Worker]                     [Redis Evaluator Worker]
         (phoenix_pipeline.py)                         (redis_evaluator.py)
                   │                                             │
                   ├─ Sequential Judge (gemma3:4b)               ├─ CPU Bi-Encoder (MiniLM)
                   ├─ 4 LLM & Retrieval Metrics                  ├─ CPU Cross-Encoder (DeBERTa)
                   │                                             ├─ 6 Mathematical Metrics
                   ▼                                             ▼
          [Arize Phoenix UI]                            [Grafana Dashboard]
        http://localhost:6006                          http://localhost:3000
                   │                                             │
                   └──────────────────────┬──────────────────────┘
                                          ▼
                            [PostgreSQL 16 Persistence]
                           (Port 5433 -> host, 5432 internal)
```

---

## Stack 1: Arize Phoenix + Gemma3:4b LLM-as-a-Judge (`phoenix_pipeline.py`)

A 100% free, local, open-source tracing and evaluation stack using **Arize Phoenix**, **OpenTelemetry**, **Redis Streams**, and a single shared instance of **`gemma3:4b`** (via Ollama or vLLM at `http://localhost:11434/v1`).

### The 4 Core Phoenix Metrics

1. **`graph_retrieval_time`**:
   - **Source:** High-resolution monotonic clock (`time.perf_counter()`) wrapped around the live `GraphAgent` retrieval step in milliseconds.
   - **Characteristics:** Microsecond precision, captures real Neo4j/Repository query traversal time without mock simulations.

2. **`tool_selection_accuracy`**:
   - **Formula:**
     $$\text{Tool Selection Accuracy} = \begin{cases} 1.0 & \text{if } \text{selected\_tool} == \text{expected\_tool} \\ 0.0 & \text{otherwise} \end{cases}$$
   - **Characteristics:** Evaluates whether the agent selected the proper tool capability (`query_knowledge_graph`, `search_botanical_catalog`, etc.) matching the ground truth requirement.

3. **`groundedness`**:
   - **Mechanics:** Calculated sequentially after generation by sending retrieved evidence claims and agent output to the local `gemma3:4b` judge under a strict JSON format prompt:
     ```json
     {"groundedness": 0.85, "hallucination_rate": 0.15, "reasoning": "Output supported by context"}
     ```
   - **Fallback:** Includes a robust local token-alignment analyzer if the local LLM server is temporarily offline.

4. **`hallucination_rate`**:
   - **Formula:**
     $$\text{Hallucination Rate} = 1.0 - \text{Groundedness}$$
   - **Characteristics:** Strictly inversely proportional to groundedness, guaranteeing mathematical consistency.

---

### Functions & Code API Reference (`phoenix_pipeline.py`)

#### 1. `execute_real_graph_retrieval(plant_id, query_type)`
* **Location:** [`evaluator/phoenix_pipeline.py`](file:///d:/Major%20Project/impark-major-project/evaluator/phoenix_pipeline.py#L295-L352)
* **Purpose:** Imports and executes the live IMPARK [`GraphAgent`](file:///d:/Major%20Project/impark-major-project/backend/agents/graph/agent.py) and [`TextAgent`](file:///d:/Major%20Project/impark-major-project/backend/agents/text/agent.py), measures monotonic retrieval latency via `time.perf_counter()`, and extracts live graph evidence claims.
* **Return:** `Tuple[Dict[str, Any], float]` (retrieved facts dictionary and latency in milliseconds).

#### 2. `execute_agent_pipeline(user_query, expected_tool, tracer, redis_client)`
* **Location:** [`evaluator/phoenix_pipeline.py`](file:///d:/Major%20Project/impark-major-project/evaluator/phoenix_pipeline.py#L354-L489)
* **Purpose:** Executes the live multi-agent workflow, generates answer via local `gemma3:4b`, attaches OpenTelemetry span attributes, pushes the trace payload to Redis Streams asynchronously, and puts the agent to sleep.
* **Return:** Trace dictionary containing `trace_id`, `span_id`, `output`, `context`, `graph_retrieval_time_ms`, and `tool_selection_accuracy`.

#### 3. `evaluate_groundedness_and_hallucination(judge_response_json, retrieved_context, agent_output)`
* **Location:** [`evaluator/phoenix_pipeline.py`](file:///d:/Major%20Project/impark-major-project/evaluator/phoenix_pipeline.py#L588-L632)
* **Purpose:** Grades groundedness and hallucination rate from `gemma3:4b` JSON judge response, validating inverse consistency (`hallucination_rate = 1.0 - groundedness`).

#### 4. `IdleAwareEvaluationJudge`
* **Location:** [`evaluator/phoenix_pipeline.py`](file:///d:/Major%20Project/impark-major-project/evaluator/phoenix_pipeline.py#L495-L733)
* **Key Methods:**
  - `evaluate_span(span_payload)`: Evaluates a single trace span, invokes the judge sequentially, logs to Arize Phoenix and PostgreSQL.
  - `log_to_phoenix(...)`: Registers evaluations in Arize Phoenix via `px.log_evaluations` and sends spans to Phoenix OTLP collector (`http://localhost:6006/v1/traces`).
  - `log_to_postgres_database(...)`: Inserts structured relational metrics and raw JSONB trace into PostgreSQL `agent_evaluations` table.
  - `start_worker_daemon(block_ms, max_evals)`: Continuous OS-level socket blocking loop (`XREAD BLOCK 0`).

#### 5. `run_worker_loop(block_ms, max_evals)`
* **Location:** [`evaluator/phoenix_pipeline.py`](file:///d:/Major%20Project/impark-major-project/evaluator/phoenix_pipeline.py#L858-L915)
* **Purpose:** Standalone runner for the Idle-Aware Judge Worker. Concurrently listens to both `phoenix-agent-traces` and `agent-logs` streams to catch all agent executions.

---

### CLI Usage & Execution Commands (`phoenix_pipeline.py`)

#### Mode 1: Run Full End-to-End Demonstration (Agent -> Queue -> Judge -> Sleep)
Executes a live agent turn, pushes the trace to Redis, awakens the sequential judge, evaluates all 4 metrics, logs to Phoenix, and prints the summary report:
```powershell
# From evaluator directory:
python phoenix_pipeline.py
```

#### Mode 2: Run Continuous Idle-Aware Judge Worker Daemon
Runs a continuous background daemon that sleeps at 0.0% CPU and wakes up whenever an agent trace arrives on Redis Streams:
```powershell
python phoenix_pipeline.py --worker
```

#### Mode 3: Execute Agent Turn Only (Trace Generation Mode)
Generates an agent trace and queues it into Redis without triggering immediate in-process evaluation (useful when the worker daemon is running in a separate process):
```powershell
python phoenix_pipeline.py --trace
```

#### Mode 4: Custom Query & Expected Tool
```powershell
python phoenix_pipeline.py --query "What are the medicinal uses of Ocimum tenuiflorum?" --tool query_knowledge_graph
```

---

## Stack 2: Grafana + CPU Semantic Evaluator (`redis_evaluator.py`)

A CPU-optimized evaluator running two lightweight transformer models (~220MB RAM total) without requiring any external LLM or cloud API keys.

### The 6 Core CPU Metrics

| Metric | Model & Mechanics | Mathematical Formula |
| :--- | :--- | :--- |
| **`retrieval_time_ms`** | Monotonic clock (`time.perf_counter()`) | $(t_{\text{end}} - t_{\text{start}}) \times 1000$ |
| **`tool_accuracy`** | Trajectory set membership | $1.0 \text{ if } \text{expected} \in \text{trajectory} \text{ else } 0.0$ |
| **`groundedness_score`** | `all-MiniLM-L6-v2` dense cosine similarity | $\max(0.0, \frac{\vec{v}_C \cdot \vec{v}_O}{\|\vec{v}_C\| \|\vec{v}_O\|}) \in [0.0, 1.0]$ |
| **`hallucination_prob`** | `nli-deberta-v3-small` contradiction probability | $\max_{s \in C} P_{\text{NLI}}(\text{Contradiction} \mid s, O)$ |
| **`answer_correctness`** | 50% Cosine Similarity + 50% NLI Entailment | $0.5 \times \text{Sim}(G, O) + 0.5 \times P_{\text{NLI}}(\text{Entail} \mid G, O)$ |
| **`context_recall`** | Clamped cosine similarity | $\max(0.0, \frac{\vec{v}_G \cdot \vec{v}_C}{\|\vec{v}_G\| \|\vec{v}_C\|}) \in [0.0, 1.0]$ |

---

### Functions & Code API Reference (`redis_evaluator.py`)

* **`EvaluatorMetricsEngine`**:
  - `calculate_groundedness(context, output)`: Computes 384-dimensional dense cosine similarity using sentence transformers.
  - `calculate_hallucination_probability(context, output)`: Partitions context with `split_into_sentences()` and computes DeBERTa cross-encoder contradiction logits.
  - `calculate_answer_correctness(ground_truth, output)`: Solves the "Negation Trap" by combining semantic similarity with directional NLI entailment.
  - `calculate_context_recall(ground_truth, context)`: Checks if gold reference facts are reflected in the retrieved context.
* **`evaluate_trace(raw_trace)`**: Orchestrates metric calculation for a single trace dictionary.
* **`EvaluatorWorker.run()`**: Infinite blocking `XREAD BLOCK 0` consumer loop.

#### Running the CPU Evaluator:
```powershell
python redis_evaluator.py
```

---

### Grafana Dashboard & Pre-Configured Provisioning

Grafana automatically provisions datasources and dashboards upon boot via `grafana/provisioning/`:

* **Dashboard URL:** [http://localhost:3000](http://localhost:3000)
* **Credentials:** `admin` / `admin`
* **Pre-Configured Panels:**
  - 5 Real-Time KPI Gauges (Tool Accuracy, Groundedness, Hallucination Rate, Answer Correctness, Context Recall)
  - Time-Series Latency Graph (`retrieval_time_ms`)
  - Groundedness vs. Hallucination Trend Chart
  - Live PostgreSQL JSONB Raw Trace Inspector Table

---

## Quickstart: Local & Docker Deployment

### Step 1: Start Infrastructure Containers (Redis, Postgres, Phoenix, Grafana)

```powershell
cd evaluator
docker compose up -d
```

Containers launched:
* `eval-redis`: Redis 7 running on port `6379` (append-only persistence).
* `eval-postgres`: PostgreSQL 16 running on host port `5433` (internal port `5432`) to avoid conflicts with existing local databases.
* `eval-phoenix`: Arize Phoenix on port `6006` (UI) and port `4317` (OTLP gRPC).
* `eval-grafana`: Grafana on port `3000` with auto-loaded dashboards.

### Step 2: Install Python Dependencies

```powershell
# From repository root with active virtualenv:
.\.venv\Scripts\python.exe -m pip install -r evaluator/requirements.txt
```

### Step 3: Run the Evaluator Pipelines

#### Option A: Arize Phoenix + Gemma3:4b LLM-as-a-Judge Pipeline
```powershell
python evaluator/phoenix_pipeline.py
```
Open **[http://localhost:6006](http://localhost:6006)** to inspect spans and evaluations.

#### Option B: CPU Semantic Evaluator + Grafana Pipeline
```powershell
# Start the CPU worker:
python evaluator/redis_evaluator.py

# In another terminal, run test simulation:
python evaluator/test_pipeline.py
```
Open **[http://localhost:3000](http://localhost:3000)** (admin / admin) to view Grafana metrics.

---

## Cloud Migration & EC2 Deployment (1-Command Automation)

To deploy the complete evaluator stack to an AWS EC2 instance (Ubuntu 22.04 / 24.04 or Amazon Linux 2023 on `t3.medium`):

### 1. Configure Inbound Rules in AWS Security Group
* Port `3000` (Grafana Dashboard)
* Port `6006` (Arize Phoenix UI)
* Port `22` (SSH)

### 2. Execute 1-Command Deployment Script
```bash
git clone <your-repository-url>
cd impark-major-project/evaluator
chmod +x deploy_ec2.sh
./deploy_ec2.sh
```

The script automatically:
1. Detects Linux distribution and installs Docker Engine & Docker Compose.
2. Configures kernel overcommit memory (`sysctl vm.overcommit_memory=1`) for Redis performance.
3. Builds and starts all four containers (`eval-redis`, `eval-postgres`, `eval-phoenix`, `eval-grafana`).
4. Executes the automated verification suite.
5. Prints direct access links to your Cloud Grafana and Phoenix dashboards.

---

## Live Agentic Orchestrator Telemetry (Zero Hardcoding)

All metrics are captured dynamically during real agent executions:

```
[Agent Query]
      │
      ├─ GraphAgent (backend/agents/graph/agent.py)
      │    * t_start = time.perf_counter()
      │    * Executes typed Neo4j graph retrieval
      │    * Measures real elapsed_ms
      │    * Emits context_snippets from retrieved evidence claims
      │
      ├─ TextAgent (backend/agents/text/agent.py)
      │    * t_start = time.perf_counter()
      │    * Normalizes botanical query and searches aliases
      │    * Emits candidate labels and confidence scores
      │
      ├─ ImageAgent (backend/agents/image/agent.py)
      │    * t_start = time.perf_counter()
      │    * Performs CNN / vector image inference
      │    * Emits top predicted candidates and claims
      │
      ▼
[DeepAgentRuntime (backend/orchestrator/deepagents/runtime.py)]
      * Records tool nodes visited and monotonic latencies
      * Aggregates claims into manual_context
      * ONLY publishes if tracer.actions_performed > 0
      * Streams consolidated trace to 'agent-logs' and 'phoenix-agent-traces'
```

---

## Automated Verification & Test Suites

The evaluator includes exhaustive automated test suites covering all metric calculations, queues, and worker lifecycles.

### 1. Run Phoenix Pipeline Verification Suite
```powershell
pytest evaluator/test_phoenix_pipeline.py -v
```
Tests verified:
- `test_metric_1_graph_retrieval_time`: Asserts live retrieval latency > 0 using real agent execution.
- `test_metric_2_tool_selection_accuracy`: Asserts 1.0 on match and 0.0 on mismatch.
- `test_metrics_3_and_4_groundedness_and_hallucination_rate`: Asserts mathematical inverse consistency and strict JSON parsing.
- `test_redis_stream_span_exporter_queue`: Asserts non-blocking queueing into Redis Stream.
- `test_idle_aware_worker_single_item_lifecycle`: Asserts Start -> Evaluate -> Commit -> Sleep lifecycle.

### 2. Run CPU Evaluator & Flow Simulation Suite
```powershell
pytest evaluator/test_pipeline.py -v
```
Tests verified:
- `test_sentence_splitter`: Verifies robust sentence chunking without splitting abbreviations.
- `test_flow_1_live_chat_simulation`: Verifies live chat telemetry (nullifies ground-truth KPIs without corruption).
- `test_flow_2_offline_benchmark_simulation`: Verifies golden benchmark evaluation across all 6 metrics.
- `test_live_docker_integration`: Verifies connectivity to Redis and PostgreSQL containers.

### 3. Run All Evaluator Tests Together
```powershell
pytest evaluator/ -v
```

---

## Infrastructure Ports, Credentials & Environment Variables

### Port Allocations

| Service | Host Port | Internal Port | URL / Access | Description |
| :--- | :--- | :--- | :--- | :--- |
| **Arize Phoenix** | `6006` | `6006` | <http://localhost:6006> | Traces, spans, and LLM evaluation UI |
| **Arize Phoenix OTLP** | `4317` | `4317` | `http://localhost:4317` | OTLP gRPC telemetry collector |
| **PostgreSQL** | `5433` | `5432` | `localhost:5433` | Persistent storage (`phoenix`, `eval_db`) |
| **Redis** | `6379` | `6379` | `localhost:6379` | Streams: `phoenix-agent-traces`, `agent-logs` |
| **Grafana** | `3000` | `3000` | <http://localhost:3000> | `admin` / `admin` (Provisioned dashboards) |

### Environment Configuration (`evaluator/.env`)

Copy `evaluator/.env.example` to `evaluator/.env` to customize settings:

```ini
# Local LLM Server (Ollama / vLLM)
OPENAI_BASE_URL=http://localhost:11434/v1
OPENAI_API_KEY=ollama
AGENT_MODEL=gemma3:4b
EVAL_MODEL=gemma3:4b

# Redis Streams Configuration
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_STREAM=phoenix-agent-traces
REDIS_LEGACY_STREAM=agent-logs

# PostgreSQL Unified Storage Configuration
EVAL_POSTGRES_PORT=5433
POSTGRES_HOST=localhost
POSTGRES_PORT=5433
POSTGRES_USER=postgres
POSTGRES_PASSWORD=password
POSTGRES_DB=phoenix
EVAL_POSTGRES_DB=eval_db

# Arize Phoenix Configuration
PHOENIX_ENDPOINT=http://localhost:6006
PHOENIX_PROJECT_NAME=impark-deepagents
```
