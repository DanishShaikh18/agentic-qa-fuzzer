"""
Model Context Protocol (MCP) Server for the Agentic QA Fuzzer Execution Arm.

SANDBOX ISOLATION PATTERN & ARCHITECTURE:
--------------------------------------------------------------------------------
This server acts as the decoupled, defensive execution sandbox for the AI Attacker
Agent. By isolating execution primitives (HTTP requests, file system writes, schema
fetching) within an explicit MCP server over standard JSON-RPC 2.0 primitives/pipes:
1. Security & Decoupling: The AI reasoning engine (ReAct/LangGraph) operates in a
   pure cognitive environment without raw OS or socket access. It interacts strictly via
   strongly-typed tool abstractions.
2. Defensive Fault Isolation: Unhandled exceptions or socket timeouts during network
   attacks are intercepted within the execution arm and translated into structured
   string payloads. This prevents network panics or target server crashes from halting
   the orchestrating LLM loop.
3. Clean Boundary: Zero dependency on LangChain or LangGraph components, maintaining
   strict separation of concerns between agent state orchestration and tool execution.
"""

import json
import re
import sys
from pathlib import Path
from typing import Any

# Ensure local virtual environment dependencies are accessible even if run via global Python
_workspace_root = Path(__file__).resolve().parent.parent.parent
_venv_site_packages = _workspace_root / ".venv" / "Lib" / "site-packages"
if _venv_site_packages.exists() and str(_venv_site_packages) not in sys.path:
    sys.path.insert(0, str(_venv_site_packages))

import httpx
from fastmcp import FastMCP

# Initialize FastMCP Server instance
mcp = FastMCP("FuzzerExecutionArm")


@mcp.tool()
async def fetch_api_schema(base_url: str) -> str:
    """
    Downloads the raw OpenAPI specification from the target FastAPI microservice.

    Args:
        base_url: The root URL of the target microservice (e.g., "http://localhost:8000").

    Returns:
        The raw JSON text of the OpenAPI schema, or a formatted error message string.
    """
    url = f"{base_url.rstrip('/')}/openapi.json"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.text
    except httpx.HTTPStatusError as exc:
        return f"Error: Target server returned HTTP status {exc.response.status_code} when fetching schema."
    except httpx.RequestError as exc:
        return f"Error: Target server unreachable at connection step ({exc})."
    except Exception as exc:
        return f"Error: Unexpected exception while fetching OpenAPI schema: {exc}"


@mcp.tool()
async def fire_http_request(
    method: str,
    url: str,
    payload: dict[str, Any] | None = None,
) -> str:
    """
    The adversarial execution module. Executes an HTTP request against a specific endpoint
    string with a mutated payload provided by the AI agent.

    Args:
        method: HTTP request method (e.g., "GET", "POST", "PUT", "DELETE").
        url: The full target endpoint URL string.
        payload: Optional JSON body dictionary (for POST/PUT) or query parameter dictionary (for GET).

    Returns:
        A formatted string capturing the HTTP status code and raw response body.
    """
    if payload is None:
        payload = {}

    upper_method = method.upper()
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            if upper_method == "GET":
                response = await client.request(upper_method, url, params=payload)
            else:
                response = await client.request(upper_method, url, json=payload)

            # Return status code and response body explicitly even on 500 Internal Server Errors
            # so the AI agent can verify that it broke the application.
            return (
                f"HTTP_STATUS_CODE: {response.status_code}\n"
                f"RESPONSE_BODY: {response.text}"
            )
    except httpx.RequestError as exc:
        return f"Error: HTTP request failed due to network or connection issue: {exc}"
    except Exception as exc:
        return f"Error: Unexpected runtime failure executing HTTP request: {exc}"


@mcp.tool()
async def save_test_case(
    endpoint: str,
    method: str,
    payload: dict[str, Any] | None = None,
) -> str:
    """
    Writes a standalone, clean automation script to disk once a vulnerability has been verified.

    Args:
        endpoint: The API endpoint path where the vulnerability was discovered (e.g., "/profiles/update").
        method: The HTTP method used to trigger the vulnerability.
        payload: The specific JSON payload or query parameters that caused the 500 error.

    Returns:
        A confirmation string indicating the file location, or an error message if saving failed.
    """
    if payload is None:
        payload = {}

    try:
        # Dynamically generate clean filename from endpoint string
        clean_name = re.sub(r"[^a-zA-Z0-9_]", "_", endpoint.strip("/"))
        if not clean_name:
            clean_name = "root"
        filename = f"test_vulnerability_{clean_name}.py"

        # Check standard container mount (/app/generated-tests) vs local sibling directory
        container_dir = Path("/app/generated-tests")
        local_dir = Path("generated-tests")
        output_dir = container_dir if Path("/app").exists() else local_dir
        output_dir.mkdir(parents=True, exist_ok=True)

        file_path = output_dir / filename

        upper_method = method.upper()
        payload_repr = json.dumps(payload, indent=4)

        # Generate standalone pytest regression artifact
        test_code = f'''"""
Autonomous regression test artifact generated by Agentic QA Fuzzer.

Target Endpoint: {endpoint}
HTTP Method: {upper_method}
Fuzzing Payload: {payload_repr}

Automated Test Boundary:
This test asserts that the target endpoint does NOT crash with an unhandled
HTTP 500 Internal Server Error when processing this edge-case input.
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

    # Assert regression boundary: Server must handle errors gracefully without a 500 crash
    assert response.status_code != 500, (
        f"Regression Failure: Endpoint triggered unhandled HTTP 500 Internal Server Error.\\n"
        f"Status Code: {{response.status_code}}\\n"
        f"Response Body: {{response.text}}"
    )
'''
        file_path.write_text(test_code, encoding="utf-8")
        return f"Successfully generated regression test case at: {file_path.resolve()}"
    except Exception as exc:
        return f"Error: Failed to save regression test case to disk: {exc}"


if __name__ == "__main__":
    # Execute the FastMCP server over standard I/O pipes
    mcp.run()
