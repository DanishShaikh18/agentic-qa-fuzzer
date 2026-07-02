"""
Core AI Orchestration Engine for Agentic QA Fuzzer.

LANGGRAPH REASONING + ACTING (ReAct) ARCHITECTURE:
--------------------------------------------------------------------------------
1. State Machine: Built on LangGraph (`StateGraph`), tracking conversational history
   and tool executions within a strictly typed state (`FuzzerState`).
2. Adversarial Prompts: Instructs Google Gemini 2.0 Flash to systematically bypass
   standard API input validations (HTTP 422/400) by mutating payload structures until
   an unhandled runtime panic (HTTP 500 Internal Server Error) is exposed.
3. Real MCP Tool Proxying: Tools are NOT defined locally. The agent connects to the
   external `mcp_server.py` process over stdio (JSON-RPC 2.0) and discovers its tools
   at runtime via `langchain-mcp-adapters`. The LLM never touches httpx or the
   filesystem directly — it only ever sees MCP tool schemas.
4. Production Guardrails: Enforces a strict execution graph recursion limit
   (`recursion_limit`, from config) to prevent runaway autonomous loops.
"""

from pathlib import Path
from typing import Annotated, Any, TypedDict

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

try:
    from .config import settings
except ImportError:
    from config import settings


# ==========================================
# 1. State Definition
# ==========================================


class FuzzerState(TypedDict):
    """Represents the internal state of the autonomous fuzzing graph."""

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
# 3. MCP Client Configuration
# ==========================================

# Path to the MCP server script this agent spawns as a subprocess over stdio.
_MCP_SERVER_SCRIPT = str(Path(__file__).resolve().parent / "mcp_server.py")

mcp_client = MultiServerMCPClient(
    {
        "fuzzer_tools": {
            "command": "python",
            "args": [_MCP_SERVER_SCRIPT],
            "transport": "stdio",
        }
    }
)

# LLM instantiated once at module load, not on every graph iteration.
llm = ChatGoogleGenerativeAI(
    model="gemini-2.0-flash",
    google_api_key=settings.GEMINI_API_KEY,
    temperature=0.1,
)


# ==========================================
# 4. Graph Nodes & Routing
# ==========================================


def should_continue(state: FuzzerState) -> str:
    """Router: goes to 'tools' if the LLM emitted tool calls, otherwise terminates."""
    last_message = state["messages"][-1]
    if getattr(last_message, "tool_calls", None):
        return "tools"
    return END


async def build_graph():
    """
    Discovers tools from the MCP server, binds them to the LLM, and compiles
    the LangGraph state machine. Must be awaited once before the graph is used,
    since MCP tool discovery is an async handshake over stdio.
    """
    tools = await mcp_client.get_tools()
    llm_with_tools = llm.bind_tools(tools)
    tool_node = ToolNode(tools)

    async def reasoning_node(state: FuzzerState) -> dict[str, Any]:
        messages = state["messages"]
        if not any(isinstance(m, SystemMessage) for m in messages):
            messages = [SystemMessage(content=SYSTEM_PROMPT)] + list(messages)
        response = await llm_with_tools.ainvoke(messages)
        return {"messages": [response]}

    workflow = StateGraph(FuzzerState)
    workflow.add_node("reasoning", reasoning_node)
    workflow.add_node("tools", tool_node)

    workflow.add_edge(START, "reasoning")
    workflow.add_conditional_edges("reasoning", should_continue, ["tools", END])
    workflow.add_edge("tools", "reasoning")

    return workflow.compile()


# ==========================================
# 5. Entrypoint
# ==========================================


async def run_fuzzer(target_url: str = "http://localhost:8000") -> dict[str, Any]:
    """
    Executes the Agentic QA Fuzzer against a target microservice with strict
    recursion limits, using real MCP tools discovered from mcp_server.py.

    Args:
        target_url: The root URL of the target API.

    Returns:
        The final terminal graph state dictionary.
    """
    graph = await build_graph()

    initial_state: FuzzerState = {
        "messages": [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(
                content=f"Begin autonomous fuzzing session against target URL: {target_url}"
            ),
        ],
        "target_url": target_url,
    }

    config = {"recursion_limit": settings.MAX_RECURSION_LIMIT}
    return await graph.ainvoke(initial_state, config=config)


if __name__ == "__main__":
    import asyncio

    target_endpoint = settings.TARGET_API_URL
    print(f"[*] Initializing Agentic QA Fuzzer against: {target_endpoint}")
    final_state = asyncio.run(run_fuzzer(target_endpoint))
    print("[+] Fuzzing session terminated. Final summary:")
    print(final_state["messages"][-1].content)