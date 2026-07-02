from typing import Any
from fastapi import FastAPI
from pydantic import BaseModel, Field

app = FastAPI(
    title="Victim API",
    description="Target microservice containing intentional edge-case vulnerabilities for AI fuzzing.",
    version="1.0.0",
)


# ==========================================
# Pydantic Request Models
# ==========================================


class ProfileUpdateRequest(BaseModel):
    username: str = Field(..., description="The username associated with the profile.")
    account_id: int = Field(..., description="Unique numerical account identifier.")
    metadata: dict[str, Any] | None = Field(
        default=None,
        description="Optional arbitrary dictionary containing profile metadata.",
    )


class OrderProcessRequest(BaseModel):
    item_id: str = Field(..., description="Unique alphanumeric item SKU/ID.")
    quantities: list[int] = Field(
        ...,
        description="List of integer quantities representing batch items in the order.",
    )


# ==========================================
# Endpoints with Intentional Vulnerabilities
# ==========================================


@app.post("/profiles/update")
async def update_profile(profile: ProfileUpdateRequest):
    """
    Modifies a user profile.

    VULNERABILITY 1: Unhandled AttributeError (Null Pointer Dereference equivalent)
    -----------------------------------------------------------------------------
    If the request body explicitly passes `"metadata": null` (or omits it when default is None),
    Pydantic assigns `profile.metadata = None`. This passes all 422 validation checks.
    However, the handler directly calls `.get()` on `profile.metadata` without checking
    if `profile.metadata` is `None` first.

    Trigger Payload: {"username": "test", "account_id": 123, "metadata": null}
    Result: AttributeError: 'NoneType' object has no attribute 'get' -> HTTP 500
    """
    # INTENTIONAL BUG: Attempting method lookup on a potentially None field without checking
    if "override" in profile.metadata.get("flags", {}):
        return {
            "status": "success",
            "message": f"Profile {profile.username} updated with admin override.",
        }

    return {
        "status": "success",
        "message": f"Profile {profile.username} (Account: {profile.account_id}) updated successfully.",
    }


@app.get("/analytics/division")
async def calculate_division(numerator: int, denominator: int):
    """
    Runs standard mathematical metric operations.

    VULNERABILITY 2: Unhandled ZeroDivisionError
    -----------------------------------------------------------------------------
    FastAPI and Pydantic successfully validate that both query parameters (`numerator`
    and `denominator`) are valid integers (avoiding a 422 validation failure).
    However, the handler omits any validation checking for `denominator == 0`.

    Trigger Payload: GET /analytics/division?numerator=100&denominator=0
    Result: ZeroDivisionError: division by zero -> HTTP 500
    """
    # INTENTIONAL BUG: Executing mathematical division without checking for zero denominator
    result = numerator / denominator

    return {
        "operation": "division",
        "numerator": numerator,
        "denominator": denominator,
        "result": result,
    }


@app.post("/orders/process")
async def process_order(order: OrderProcessRequest):
    """
    Simulates an e-commerce batch order request.

    VULNERABILITY 3: Unhandled IndexError (Empty List Access)
    -----------------------------------------------------------------------------
    Pydantic validates that `quantities` is a list of integers (`list[int]`).
    By default, an empty array `[]` is a valid `list[int]` and passes 422 validation.
    The handler assumes the list is non-empty and directly indexes `order.quantities[0]`.

    Trigger Payload: {"item_id": "SKU-999", "quantities": []}
    Result: IndexError: list index out of range -> HTTP 500
    """
    # INTENTIONAL BUG: Direct index lookup on a list without verifying len(order.quantities) > 0
    primary_quantity = order.quantities[0]

    total_items = sum(order.quantities)

    return {
        "status": "processed",
        "item_id": order.item_id,
        "primary_batch_size": primary_quantity,
        "total_units": total_items,
    }
