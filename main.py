from fastapi import FastAPI, Request, Header, HTTPException
from fastapi.responses import JSONResponse, Response
from fastapi.middleware.cors import CORSMiddleware

from collections import defaultdict, deque
from threading import Lock
import time
import math
import base64

app = FastAPI()

# -----------------------------
# CONFIG
# -----------------------------
TOTAL_ORDERS = 52
RATE_LIMIT = 18
RATE_WINDOW_SECONDS = 10

ALLOWED_ORIGINS = ["*"]

# -----------------------------
# CORS
# -----------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Retry-After"],
)

# -----------------------------
# In-memory storage
# -----------------------------
orders = []
idempotency_store = {}

rate_buckets = defaultdict(deque)
state_lock = Lock()

# fixed catalog
catalog = [{"id": i, "item": f"Order {i}"} for i in range(1, TOTAL_ORDERS + 1)]

# -----------------------------
# Rate limit middleware
# -----------------------------
@app.middleware("http")
async def per_client_rate_limit(request: Request, call_next):

    if request.method == "OPTIONS":
        return await call_next(request)

    client_id = request.headers.get("X-Client-Id", "anonymous")
    now = time.monotonic()

    with state_lock:
        bucket = rate_buckets[client_id]

        while bucket and now - bucket[0] >= RATE_WINDOW_SECONDS:
            bucket.popleft()

        if len(bucket) >= RATE_LIMIT:

            retry_after = max(
                1,
                math.ceil(RATE_WINDOW_SECONDS - (now - bucket[0]))
            )

            headers = {
                "Retry-After": str(retry_after)
            }

            return Response(
                status_code=429,
                content='{"detail":"Rate limit exceeded"}',
                media_type="application/json",
                headers=headers
            )

        bucket.append(now)

    response = await call_next(request)
    return response


# -----------------------------
# POST /orders
# -----------------------------
@app.post("/orders", status_code=201)
def create_order(
    request: dict,
    idempotency_key: str = Header(...)
):

    if idempotency_key in idempotency_store:
        return idempotency_store[idempotency_key]

    order = {
        "id": len(orders) + 1,
        **request
    }

    orders.append(order)
    idempotency_store[idempotency_key] = order

    return order


# -----------------------------
# GET /orders
# -----------------------------
@app.get("/orders")
def get_orders(limit: int = 10, cursor: str | None = None):

    start = 0

    if cursor:
        start = int(base64.b64decode(cursor).decode())

    items = catalog[start:start + limit]

    next_cursor = None

    if start + limit < len(catalog):
        next_cursor = base64.b64encode(
            str(start + limit).encode()
        ).decode()

    return {
        "items": items,
        "next_cursor": next_cursor
    }
