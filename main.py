from fastapi import FastAPI, Request, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from typing import Optional, Dict, List
import time
import uuid

app = FastAPI()

# Configure CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Retry-After"],
)

# Configuration constants
TOTAL_ORDERS = 52
RATE_LIMIT = 18
WINDOW = 10

# In-memory storage
orders_store: Dict[int, Dict] = {}
idempotency_store: Dict[str, Dict] = {}
rate_store: Dict[str, List[float]] = {}

for i in range(1, TOTAL_ORDERS + 1):
    orders_store[i] = {"id": i, "item": f"order_item_{i}"}


# Rate limiting logic
def check_rate_limit(client_id: str):
    now = time.time()

    if client_id not in rate_store:
        rate_store[client_id] = []

    # Keep requests from the specified time window
    rate_store[client_id] = [
        t for t in rate_store[client_id]
        if now - t < WINDOW
    ]

    if len(rate_store[client_id]) >= RATE_LIMIT:
        retry_after = int(WINDOW - (now - rate_store[client_id][0]))
        retry_after = max(1, retry_after)

        return JSONResponse(
            status_code=429,
            content={"error": "rate limit exceeded"},
            headers={"Retry-After": str(retry_after)}
        )

    rate_store[client_id].append(now)
    return None


@app.post("/orders")
async def create_order(
    idempotency_key: Optional[str] = Header(None),
    x_client_id: Optional[str] = Header(None),
):
    if not x_client_id:
        return JSONResponse(status_code=400, content={"error": "missing client id"})

    rate_resp = check_rate_limit(x_client_id)
    if rate_resp:
        return rate_resp

    if not idempotency_key:
        return JSONResponse(status_code=400, content={"error": "missing idempotency key"})

    if idempotency_key in idempotency_store:
        return idempotency_store[idempotency_key]

    order = {
        "id": str(uuid.uuid4()),
        "status": "created"
    }

    idempotency_store[idempotency_key] = order

    return JSONResponse(status_code=201, content=order)


@app.get("/orders")
async def get_orders(
    limit: int = 10,
    cursor: Optional[str] = None,
    x_client_id: Optional[str] = Header(None),
):
    if not x_client_id:
        return JSONResponse(status_code=400, content={"error": "missing client id"})

    rate_resp = check_rate_limit(x_client_id)
    if rate_resp:
        return rate_resp

    start = int(cursor) if cursor else 1
    end = min(start + limit - 1, TOTAL_ORDERS)

    items = [orders_store[i] for i in range(start, end + 1)]

    next_cursor = str(end + 1) if end < TOTAL_ORDERS else None

    return {
        "items": items,
        "next_cursor": next_cursor
    }