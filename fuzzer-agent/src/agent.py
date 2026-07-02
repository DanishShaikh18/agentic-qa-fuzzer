"""
Core AI Orchestration Engine for Agentic QA Fuzzer.

LANGGRAPH REASONING + ACTING (ReAct) ARCHITECTURE:
--------------------------------------------------------------------------------
This module implements the stateful Evaluator-Optimizer loop driving the AI Attacker:
1. State Machine: Built on LangGraph (`StateGraph`), tracking conversational history
   and tool executions within a strictly typed state (`FuzzerState`).
2. Adversarial Prompts: Instructs Google Gemini 2.0 Flash to systematically bypass
   standard API input validations (HTTP 422/400) by mutating payload structures until
   an unhandled runtime panic (HTTP 500 Internal Server Error) is exposed.
3. Decoupled Tool Proxying: Proxies tool calls to the target microservice / execution
   arm and automatically generates pytest regression suites upon discovering bugs.
4. Production Guardrails: Enforces a strict execution graph recursion limit (`recursion_limit=25`)
   to prevent runaway autonomous loops and control LLM token consumption.
"""

import json
import os
import re
import sys
from pathlib import Path
from typing import Annotated, Any, TypedDict

# Ensure local virtual environment dependencies are accessible even if run via global Python
_workspace_root = Path(__file__).resolve().parent.parent.parent
_venv_site_packages = _workspace_root / ".venv" / "Lib" / "site-packages"
if _venv_site_packages.exists() and str(_venv_site_packages) not in sys.path:
    sys.path.insert(0, str(_venv_site_packages))

import httpx
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_core.tools import tool
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode


# ==========================================
# 1. State Definition
# ==========================================


class FuzzerState(TypedDict):
    """
    Represents the internal state of the autonomous fuzzing graph.
    """

    messages: Annotated[list[BaseMessage], add_messages]
    target_url: str


# ==========================================
# 2. Adversarial System Prompt
# ==========================================

SYSTEM_PROMPT = """You are an autonomous AI Penetration Tester and Automated Security Fuzzer.
Your mission is to systematically discover unhandled server exceptions (HTTP 500 Internal Server Errors) in target API endpoints.

CORE EXECUTION STRATEGY:
1. Reconnaissance: Call `fetch_api_schema` to download and analyze the OpenAPI specification.
2. Attack Execution: Use `fire_http_request` to send structured payloads against target routes.
3. Evaluator-Optimizer Loop:
   - If an endpoint returns HTTP 422 (Unprocessable Entity) or HTTP 400 (Bad Request), your payload was intercepted by standard validation middleware.
   - Analyze schema boundaries and craft mutated edge-case inputs (e.g., boundary integers like 0 or negative numbers, `null` values where dictionaries are expected, empty lists `[]`, or malformed types) to bypass validation and trigger internal code panics.
   - Continue mutating until you achieve an HTTP 500 Internal Server Error.
4. Regression Capture: Once you trigger an HTTP 500 error, you MUST immediately execute `save_test_case` passing the exact endpoint, HTTP method, and payload that caused the crash.
5. Termination: After successfully saving the regression test case, output a concise vulnerability report and cease further tool invocations."""


# ==========================================
# 3. Tool Client Mocking (Proxy Definitions)
# ==========================================


@tool
def fetch_api_schema(base_url: str) -> str:
    """Downloads the raw OpenAPI specification from the target FastAPI microservice."""
    try:
        url = f"{base_url.rstrip('/')}/openapi.json"
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(url)
            resp.raise_for_status()
            return resp.text
    except Exception as exc:
        return f"Error fetching OpenAPI schema: {exc}"


@tool
def fire_http_request(
    method: str, url: str, payload: dict[str, Any] | None = None
) -> str:
    """Executes a raw HTTP request against a specific endpoint string with a mutated payload provided by the AI."""
    if payload is None:
        payload = {}
    upper_method = method.upper()
    try:
        with httpx.Client(timeout=10.0) as client:
            if upper_method == "GET":
                resp = client.request(upper_method, url, params=payload)
            else:
                resp = client.request(upper_method, url, json=payload)
            return f"HTTP_STATUS_CODE: {resp.status_code}\nRESPONSE_BODY: {resp.text}"
    except Exception as exc:
        return f"Error executing HTTP request: {exc}"


@tool
def save_test_case(
    endpoint: str, method: str, payload: dict[str, Any] | None = None
) -> str:
    """Writes a standalone pytest regression automation script to disk once a vulnerability has been verified."""
    if payload is None:
        payload = {}
    try:
        clean_name = re.sub(r"[^a-zA-Z0-9_]", "_", endpoint.strip("/")) or "root"
        filename = f"test_vulnerability_{clean_name}.py"

        container_dir = Path("/app/generated-tests")
        local_dir = Path("generated-tests")
        output_dir = container_dir if Path("/app").exists() else local_dir
        output_dir.mkdir(parents=True, exist_ok=True)

        file_path = output_dir / filename
        upper_method = method.upper()
        payload_repr = json.dumps(payload, indent=4)

        test_code = f'''"""
Autonomous regression test generated by Agentic QA Fuzzer.
Target Endpoint: {endpoint}
Method: {upper_method}
Payload: {payload_repr}
"""
import pytest
import httpx

TARGET_BASE_URL = "http://victim-api:8000"


@pytest.mark.asyncio
async def test_vulnerability_regression():
    url = f"{{TARGET_BASE_URL}}{endpoint}"
    payload = {payload_repr}

    async with httpx.AsyncClient(timeout=10.0) as client:
        if "{upper_method}" == "GET":
            response = await client.request("{upper_method}", url, params=payload)
        else:
            response = await client.request("{upper_method}", url, json=payload)

    assert response.status_code != 500, (
        f"Regression Failure: Endpoint triggered unhandled HTTP 500 Internal Server Error.\\n"
        f"Status Code: {{response.status_code}}\\n"
        f"Response Body: {{response.text}}"
    )
'''
        file_path.write_text(test_code, encoding="utf-8")
        return f"Successfully generated regression test case at: {file_path.resolve()}"
    except Exception as exc:
        return f"Error saving regression test case: {exc}"


# ==========================================
# 4. Graph Nodes & Routing
# ==========================================

tools = [fetch_api_schema, fire_http_request, save_test_case]
tool_execution_node = ToolNode(tools)


def reasoning_node(state: FuzzerState) -> dict[str, Any]:
    """
    Invokes the Google Gemini model bound with execution tools using current state messages.
    """
    llm = ChatGoogleGenerativeAI(
        model="gemini-2.0-flash",
        temperature=0.1,
    ).bind_tools(tools)

    messages = state["messages"]
    # Ensure system instructions precede all conversational messages
    if not any(isinstance(m, SystemMessage) for m in messages):
        messages = [SystemMessage(content=SYSTEM_PROMPT)] + list(messages)

    response = llm.invoke(messages)
    return {"messages": [response]}


def should_continue(state: FuzzerState) -> str:
    """
    Router function: routes to 'tools' if the LLM invoked tool calls, otherwise terminates to 'END'.
    """
    last_message = state["messages"][-1]
    if getattr(last_message, "tool_calls", None):
        return "tools"
    return END


# ==========================================
# 5. Graph Compilation & Guardrails
# ==========================================

workflow = StateGraph(FuzzerState)

workflow.add_node("reasoning", reasoning_node)
workflow.add_node("tools", tool_execution_node)

workflow.add_edge(START, "reasoning")
workflow.add_conditional_edges("reasoning", should_continue, ["tools", END])
workflow.add_edge("tools", "reasoning")

graph = workflow.compile()


def run_fuzzer(target_url: str = "http://localhost:8000") -> dict[str, Any]:
    """
    Executes the Agentic QA Fuzzer against a target microservice with strict recursion limits.

    Args:
        target_url: The root URL of the target API.

    Returns:
        The final terminal graph state dictionary.
    """
    initial_state: FuzzerState = {
        "messages": [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(
                content=f"Begin autonomous fuzzing session against target URL: {target_url}"
            ),
        ],
        "target_url": target_url,
    }

    # Production Guardrail: Enforce recursion limit to prevent infinite loops
    config = {"recursion_limit": 25}
    return graph.invoke(initial_state, config=config)


if __name__ == "__main__":
    target_endpoint = os.getenv("VICTIM_API_URL", "http://localhost:8000")
    print(f"[*] Initializing Agentic QA Fuzzer against: {target_endpoint}")
    final_state = run_fuzzer(target_endpoint)
    print("[+] Fuzzing session terminated. Final summary:")
    print(final_state["messages"][-1].content)
