# Agentic QA Fuzzer

An autonomous API fuzzing agent that uses an LLM (Gemini 2.0 Flash) to discover unhandled server exceptions in REST APIs. Unlike traditional fuzzers that rely on random or grammar-based input generation, this system reads the target's OpenAPI schema, understands validation boundaries, and iteratively mutates payloads to bypass input validation (422/400) and escalate to unhandled crashes (500). When it finds one, it writes a standalone pytest regression test to disk automatically.

## Architecture

The core design decision is **strict isolation between reasoning and execution**. The LLM never makes HTTP requests or touches the filesystem directly. All tool execution is proxied through a Model Context Protocol (MCP) server running as a subprocess, communicating over stdio (JSON-RPC 2.0).

```
                        LangGraph StateGraph
                    ┌─────────────────────────┐
                    │                         │
                    │   ┌───────────────┐     │
         START ────►│   │  Reasoning    │     │
                    │   │  (Gemini LLM) │     │
                    │   └──────┬────────┘     │
                    │          │ tool_calls?   │
                    │      ┌───┴───┐          │
                    │      │  Yes  │  No ──────────► END
                    │      └───┬───┘          │
                    │   ┌──────▼────────┐     │
                    │   │   ToolNode    │     │
                    │   │  (MCP proxy)  │     │
                    │   └──────┬────────┘     │
                    │          │              │
                    │          └──────────────┘
                    └─────────────────────────┘
                               │
                    stdio (JSON-RPC 2.0)
                               │
                    ┌──────────▼──────────┐
                    │   mcp_server.py     │
                    │   (FastMCP 3.4.2)   │
                    │                     │
                    │  fetch_api_schema   │
                    │  fire_http_request  │
                    │  save_test_case     │
                    └──────────┬──────────┘
                               │
                          httpx calls
                               │
                    ┌──────────▼──────────┐
                    │    Victim API       │
                    │  (FastAPI, :8000)   │
                    └─────────────────────┘
```

`langchain-mcp-adapters` handles the MCP client side — it spawns `mcp_server.py` as a subprocess, performs the tool discovery handshake, and converts MCP tool schemas into LangChain-compatible tool objects that LangGraph's `ToolNode` can dispatch to.

## Tech Stack

- **LangGraph** — StateGraph with ReAct-style reasoning/tool loop
- **langchain-mcp-adapters** — MCP client bridging LangGraph to external tool servers
- **FastMCP** — MCP server framework exposing tools over stdio
- **Gemini 2.0 Flash** — LLM driving adversarial payload generation (via `langchain-google-genai`)
- **FastAPI** — victim API target with intentional vulnerabilities
- **httpx** — async HTTP client for tool-side requests
- **pytest** — format for auto-generated regression tests

## How It Works

1. **Reconnaissance** — the agent calls `fetch_api_schema` to download the victim's OpenAPI spec and map all endpoints, parameter types, and validation constraints.
2. **Adversarial probing** — it calls `fire_http_request` with structured payloads. If the target returns 422 (validation rejected) or 400 (bad request), the agent analyzes why and mutates the payload to bypass validation — e.g., sending `null` where a dict is expected, empty lists `[]` where non-empty is assumed, or `0` as a denominator.
3. **Crash escalation** — mutation continues until the target returns an unhandled 500 Internal Server Error, indicating a real bug (uncaught exception in application code).
4. **Regression capture** — once a 500 is confirmed, the agent calls `save_test_case` which writes a standalone pytest script to `generated-tests/` with the exact endpoint, method, and payload that triggered the crash.
5. **Termination** — the agent outputs a vulnerability summary and the graph ends.

## Setup and Run

Requires Python 3.10+ and a [Gemini API key](https://ai.google.dev/).

```bash
# Clone and create virtual environment
git clone <repo-url> && cd agentic-qa-fuzzer
python -m venv .venv

# Install dependencies for both services
.venv/Scripts/pip install -r victim-api/requirements.txt
.venv/Scripts/pip install -r fuzzer-agent/requirements.txt

# Set your Gemini API key
echo GEMINI_API_KEY=your-key-here > .env
```

Run in two terminals from the project root:

```bash
# Terminal 1 — start the victim API
.venv/Scripts/python -m uvicorn victim-api.app.main:app --host 127.0.0.1 --port 8000

# Terminal 2 — run the fuzzer
.venv/Scripts/python fuzzer-agent/cli.py --target-url http://localhost:8000
```

On Linux/macOS, substitute `.venv/bin/` for `.venv/Scripts/`.

## Guardrails

- **Recursion limit** — the LangGraph execution enforces a configurable `recursion_limit` (default 15, set via `MAX_RECURSION_LIMIT` in `.env`) to prevent runaway autonomous loops and bound token consumption.
- **Exception isolation** — every tool in `mcp_server.py` wraps its logic in try/except and returns error strings instead of raising. A network timeout or target crash never kills the agent loop; the LLM receives the error as text and decides how to proceed.
- **MCP process boundary** — the LLM reasoning layer has zero direct access to sockets, the filesystem, or `httpx`. All side effects go through the MCP server subprocess, which acts as a capability sandbox.

## Project Structure

```
agentic-qa-fuzzer/
├── .env                          # GEMINI_API_KEY (not committed)
├── .gitignore
├── victim-api/
│   ├── requirements.txt          # fastapi, uvicorn, pydantic
│   └── app/
│       └── main.py               # FastAPI app with intentional vulnerabilities
├── fuzzer-agent/
│   ├── requirements.txt          # langgraph, langchain-mcp-adapters, fastmcp, etc.
│   ├── cli.py                    # CLI entrypoint (argparse, banner, run loop)
│   └── src/
│       ├── agent.py              # LangGraph StateGraph, MCP client config, reasoning loop
│       ├── config.py             # Environment/settings loader (dotenv + AppConfig)
│       └── mcp_server.py         # FastMCP server: fetch_api_schema, fire_http_request, save_test_case
└── generated-tests/              # Auto-generated pytest regression scripts (written by mcp_server.py)
```
