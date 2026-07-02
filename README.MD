# 🦠 Agentic QA Fuzzer 

> An autonomous, AI-driven API penetration testing and regression generation engine built with LangGraph and the Model Context Protocol (MCP).

## 🚀 Overview

Standard API fuzzing tools often fail against modern systems because they blindly blast endpoints with malformed binary strings that get instantly blocked by basic middleware validation. 

This project solves that by deploying an **Agentic AI Fuzzer**. Utilizing the ReAct framework and Google's Gemini 2.0 Flash, the agent reads a target API's OpenAPI schema, intelligently crafts edge-case payloads to bypass basic validation (422s/400s), and actively hunts for unhandled server crashes (500s). Once a vulnerability is found, the agent automatically generates a reproducible `pytest` script so developers can patch the bug and add the test to their CI/CD pipeline.

## ✨ Key Features
* **Stateful Orchestration:** Built on LangGraph to manage the Evaluator-Optimizer loop, tracking failed attempts and dynamically adjusting attack vectors.
* **Model Context Protocol (MCP):** Completely isolates the AI reasoning engine from the execution environment. The LLM interfaces with target systems securely via `fastmcp` tool abstractions.
* **Autonomous Test Generation:** Doesn't just find bugs—it writes the code to prove them. Automatically outputs structured Python test artifacts.
* **Containerized Execution:** The Attacker Agent and the Victim API run in isolated Docker networks to simulate a real-world microservice environment.

## 🛠️ Tech Stack
* **AI Orchestration:** LangGraph, LangChain, Google GenAI
* **Integration Standard:** Model Context Protocol (MCP) via `fastmcp`
* **Target Environment:** FastAPI, Uvicorn, Pydantic
* **Testing & HTTP:** PyTest, HTTPX
* **Infrastructure:** Docker, Docker Compose

## 📂 Project Structure
```text
.
├── fuzzer-agent/          # The AI Attacker (LangGraph + MCP Client)
├── victim-api/            # The Target App (FastAPI with intentional bugs)
├── generated-tests/       # Output directory for autonomous PyTest scripts
├── docker-compose.yml     # Orchestrates the isolated network
└── .env                   # API keys and environment variables
```

## ⚙️ Quick Start

### 1. Prerequisites
* **Docker** and **Docker Compose** installed
* A Google Gemini API Key

### 2. Setup
Clone the repository and set up your environment variables:

```bash
git clone https://github.com/yourusername/agentic-qa-fuzzer.git
cd agentic-qa-fuzzer
cp .env.example .env
```

Add your `GEMINI_API_KEY` to the `.env` file.

### 3. Run the Fuzzer
Spin up both the Victim API and the Attacker Agent using Docker Compose:

```bash
docker-compose up --build
```

### 4. Watch the Hunt
Check your terminal logs. You will see the agent:

1. Fetch the OpenAPI schema from the Victim API.
2. Send initial payloads and analyze the HTTP status codes.
3. Mutate payloads to bypass `422` Validation Errors.
4. Trigger a `500` Internal Server Error.
5. Save a `test_vulnerability.py` file to the `/generated-tests` folder.

## ⚠️ Disclaimer
This tool is built for educational and internal QA testing purposes only. The agent is designed to be executed against the local `victim-api` container provided in this repository. Do not point this fuzzer at external production APIs or environments you do not own.