# mini-rag

This is a minimal implementation of the RAG model for question answering.

## Requirements

- Python 3.8 or later

#### Install Dependencies

```bash
sudo apt update
sudo apt install libpq-dev gcc python3-dev
```

#### Install Python using MiniConda

1) Download and install MiniConda from [here](https://docs.anaconda.com/free/miniconda/#quick-command-line-install)
2) Create a new environment using the following command:
```bash
$ conda create -n mini-rag python=3.8
```
3) Activate the environment:
```bash
$ conda activate mini-rag
```

### (Optional) Setup you command line interface for better readability

```bash
export PS1="\[\033[01;32m\]\u@\h:\w\n\[\033[00m\]\$ "
```

## Installation

### Install the required packages

```bash
$ pip install -r requirements.txt
```

### Setup the environment variables

```bash
$ cp .env.example .env
```

Set your environment variables in the `.env` file. Like `OPENAI_API_KEY` value.

### Multihop RAG mode
- Defaults (override in `.env` or `src/.env.example`): `MULTIHOP_MAX_HOPS=2`, `MULTIHOP_PER_HOP_K=6`, `MULTIHOP_PER_HOP_EVIDENCE=3`, optional `MULTIHOP_TEMPERATURE`.
- API sample (POST `/api/v1/nlp/index/answer/{project_id}`):
  ```json
  {
    "text": "Question that needs multi-step reasoning",
    "mode": "multihop",
    "doc_type": "general",
    "multihop_hops": 2,
    "multihop_k": 6,
    "multihop_per_hop_evidence": 3
  }
  ```
- Use the “Multihop RAG” mode toggle in the UI to send these parameters.
- Example curl:
  ```bash
  curl -X POST http://localhost:5000/api/v1/nlp/index/answer/1 \
    -H "Content-Type: application/json" \
    -d '{
      "text": "What did the committee decide and when was it announced?",
      "mode": "multihop",
      "doc_type": "general",
      "multihop_hops": 2,
      "multihop_k": 6,
      "multihop_per_hop_evidence": 3
    }'
  ```

## Run Docker Compose Services

```bash
$ cd docker
$ cp .env.example .env
```

- update `.env` with your credentials



```bash
$ cd docker
$ sudo docker compose up -d
```

## Run the FastAPI server

From the project root (where `src/main.py` lives):

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 5000
```
mini-rag-app) alaa_eldeen@DESKTOP-7DLQCMS:/mnt/d/Behoos_AI/AI Projects/mini_rag/test_mini_rag/src$ ip route | grep default
default via 172.23.112.1 dev eth0 proto kernel


The chunk size/overlap you can change are passed from the API layer:

Default values for uploads are in data.py (Form defaults):
chunk_size and overlap_size defaults appear in the upload endpoints (e.g. chunk_size=400, overlap_size=50 and chunk_size=500, overlap_size=100 depending on route). Update those defaults if you want global behavior.
The processing function itself defaults in ProcessController.py:
process_file_content(..., chunk_size: int = 500, overlap_size: int = 100).


Make sure your vector database and LLM backend (e.g. Ollama) are running and that the corresponding environment variables (`VECTOR_DB_BACKEND`, `GENERATION_BACKEND`, `OPENAI_API_URL`, `GENERATION_MODEL_ID`, etc.) are set.

## Run the React frontend

The frontend lives in `./frontend` and talks to the FastAPI backend over HTTP Basic Auth.

```bash
cd frontend
npm install
npm run dev
```

By default it expects the API at `http://localhost:5000` and will prompt for credentials on the login screen.

## POSTMAN Collection

Download the POSTMAN collection from [/assets/mini-rag-app.postman_collection.json](/assets/mini-rag-app.postman_collection.json)

## Documentation

The repository includes more detailed documentation for different parts of the system:

- API reference and signals: `APIs.md`
- Frontend overview (pages, streaming, roles): `frontend/README.md`
- Authentication and roles: `docs/auth.md`
- Visibility and access control: `docs/visibility.md`
- RAG and summary pipelines: `docs/rag-summary.md`
- Streaming protocol (NDJSON, signals): `docs/streaming.md`
- Stats and analytics interpretation: `docs/stats.md`
- Database schema and relationships: `docs/schema.md`

## Prompt Injection Guard

Every chat request now passes through a lightweight prompt guard before it touches the RAG pipeline. The guard uses deterministic heuristics to block obvious jailbreak attempts such as “ignore previous instructions”, fake `<system>` tags, or large encoded payloads. You can optionally enable the [Pytector](https://github.com/MaxMLang/pytector) classifier for an additional ML-based check (Python 3.10 compatible).

Environment flags (see `.env.example` or `docker/env/.env.app`):

```
PROMPT_GUARD_ENABLED=true            # master switch
PROMPT_GUARD_PYTECTOR=false          # set to true to enable the Pytector classifier
PROMPT_GUARD_PYTECTOR_MODEL="deberta"
PROMPT_GUARD_PYTECTOR_THRESHOLD=0.75
PROMPT_GUARD_BYPASS_HEADER="X-Bypass-Prompt-Guard"
```

Admins can bypass the guard during debugging by sending the header defined in `PROMPT_GUARD_BYPASS_HEADER` with a value of `true/1`. When a prompt is blocked the backend returns a `prompt_rejected` signal and the React client shows a friendly banner asking the user to rephrase the question.

## Troubleshooting: Connection Issues with Ollama in WSL2/Windows Setup

If you're running the FastAPI app in WSL2 (Linux subsystem on Windows) and using Ollama as the backend (via `GENERATION_BACKEND="OPENAI"` with `OPENAI_API_URL` pointing to Ollama's API), you may encounter connection refused errors (e.g., `[Errno 111] Connection refused`). This is due to networking differences between WSL2 and the Windows host.

### Steps to Fix

1. **Run Ollama on Windows and Bind to All Interfaces**:
   - Install Ollama on Windows if not already done.
   - In PowerShell or Command Prompt, set the environment variable to listen on all IPs:
     ```
     $env:OLLAMA_HOST="0.0.0.0:11434"
     ```
   - Start Ollama:
     ```
     ollama serve
     ```
   - Confirm in Ollama logs: It should show `Listening on 0.0.0.0:11434`.

2. **Find the Windows Host IP from WSL2**:
   - In your WSL2 terminal, run:
     ```
     cat /etc/resolv.conf | grep nameserver | awk '{print $2}'
     ```
     This typically outputs the host IP (e.g., `172.17.0.1`).

3. **Update `.env` in Your App**:
   - Set `OPENAI_API_URL="http://<host-ip>:11434/v1"` (replace `<host-ip>` with the IP from step 2).
   - Ensure `GENERATION_MODEL_ID` matches your Ollama model (e.g., `"qwen3:4b-instruct-2507-q4_K_M"`).
   - If using a custom model, pull it in Ollama first: `ollama pull <model>`.

4. **Test Connectivity**:
   - From WSL2: `curl http://<host-ip>:11434`
   - It should respond with "Ollama is running".
   - Restart the FastAPI server and test your endpoint.

If issues persist, check Windows Firewall for port 11434 access, or ensure no VPN/proxy interferes. For more details, refer to WSL2 networking docs.
