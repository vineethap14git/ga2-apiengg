from fastapi import FastAPI, Request, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from typing import Optional
import uuid
import time
import base64

app = FastAPI()

# ---------------- CORS ----------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Retry-After"],
)

# ---------------- CONFIG ----------------

TOTAL_ORDERS = 52
RATE_LIMIT = 18
WINDOW = 10  # seconds

# ---------------- STORAGE ----------------

created_orders = {}      # idempotency_key -> order
rate_limits = {}         # client_id -> timestamps

catalog = [
    {
        "id": i,
        "item": f"Order {i}"
    }
    for i in range(1, TOTAL_ORDERS + 1)
]

# ---------------- RATE LIMIT ----------------

@app.middleware("http")
async def limit_requests(request: Request, call_next):

    # Don't rate limit CORS preflight requests
    if request.method == "OPTIONS":
        return await call_next(request)

    client = request.headers.get("X-Client-Id", "default")

    now = time.time()

    timestamps = rate_limits.get(client, [])
    timestamps = [t for t in timestamps if now - t < WINDOW]

    if len(timestamps) >= RATE_LIMIT:
        retry = max(1, int(WINDOW - (now - timestamps[0])))

        return JSONResponse(
            status_code=429,
            content={"detail": "Rate limit exceeded"},
            headers={"Retry-After": str(retry)}
        )

    timestamps.append(now)
    rate_limits[client] = timestamps

    return await call_next(request)

# ---------------- POST /orders ----------------

@app.post("/orders", status_code=201)
async def create_order(
    request: Request,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")
):

    if not idempotency_key:
        raise HTTPException(400, "Missing Idempotency-Key")

    if idempotency_key in created_orders:
        return created_orders[idempotency_key]

    body = await request.json()

    order = {
        "id": str(uuid.uuid4()),
        **body
    }

    created_orders[idempotency_key] = order

    return order

# ---------------- GET /orders ----------------

@app.get("/orders")
async def list_orders(limit: int = 10, cursor: Optional[str] = None):

    start = 0

    if cursor:
        start = int(base64.b64decode(cursor).decode())

    end = min(start + limit, TOTAL_ORDERS)

    items = catalog[start:end]

    next_cursor = None

    if end < TOTAL_ORDERS:
        next_cursor = base64.b64encode(str(end).encode()).decode()

    return {
        "items": items,
        "next_cursor": next_cursor
    }
