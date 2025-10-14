# mini-rag

This is a minimal implementation of the RAG model for question answering.

## Requirements

- Python 3.8 or later

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

```bash
$ uvicorn main:app --reload --host 0.0.0.0 --port 5000
```

## POSTMAN Collection

Download the POSTMAN collection from [/assets/mini-rag-app.postman_collection.json](/assets/mini-rag-app.postman_collection.json)

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