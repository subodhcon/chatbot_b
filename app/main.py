import time
import logging
from typing import Any
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from sqlalchemy.sql import text
import redis.asyncio as aioredis

from app.core.config import settings
from app.core.logging import setup_logging
from app.core.exceptions import setup_exception_handlers
from app.api.router import api_router
from app.db.session import get_db
from app.utils.redis import get_redis, close_redis

logger = logging.getLogger("app.request")

async def listen_to_ingestion_updates():
    """
    Subscribes to Redis 'ingestion_updates' channel and broadcasts updates to WebSocket clients.
    """
    import asyncio
    import json
    from app.utils.redis import get_redis
    from app.core.websocket import manager

    logging.info("Starting Redis pubsub listener for ingestion updates...")
    redis_generator = get_redis()
    try:
        redis_client = await redis_generator.__anext__()
    except StopAsyncIteration:
        logging.error("Failed to get Redis client from generator.")
        return

    if getattr(redis_client, "is_mock", False):
        logging.info("Redis is mocked. Skipping real-time worker pubsub listener.")
        return

    try:
        pubsub = redis_client.pubsub()
        await pubsub.subscribe("ingestion_updates")
        logging.info("Subscribed to Redis channel 'ingestion_updates'")

        while True:
            try:
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message and message.get("type") == "message":
                    data_str = message.get("data")
                    if data_str:
                        data = json.loads(data_str)
                        bot_id = data.get("bot_id")
                        if bot_id:
                            await manager.broadcast_json_to_session(f"ingestion:{bot_id}", data)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logging.error(f"Error in pubsub message loop: {e}")
                await asyncio.sleep(1)

        await pubsub.unsubscribe("ingestion_updates")
        await pubsub.close()
    except Exception as e:
        logging.error(f"Failed to initialize Redis Pub/Sub: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    import asyncio
    # Setup logging
    setup_logging()
    logging.info("Starting up FastAPI application...")
    
    # Start the ingestion updates pubsub listener
    pubsub_task = asyncio.create_task(listen_to_ingestion_updates())
    
    yield
    
    # Cancel task on shutdown
    logging.info("Cancelling Redis pubsub task...")
    pubsub_task.cancel()
    try:
        await pubsub_task
    except asyncio.CancelledError:
        pass

    # Cleanup tasks - close redis connection pool
    logging.info("Shutting down FastAPI application...")
    await close_redis()

def get_application() -> FastAPI:
    application = FastAPI(
        title=settings.PROJECT_NAME,
        openapi_url="/openapi.json",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # Bind global exception handlers
    setup_exception_handlers(application)

    # Mount static uploads path
    import os
    from fastapi.staticfiles import StaticFiles
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    application.mount("/uploads", StaticFiles(directory=settings.UPLOAD_DIR), name="uploads")

    # --- Two-tier CORS ---
    # Public widget endpoints (/api/v1/public/*) are accessed from arbitrary customer
    # domains, so they need allow_origins=["*"]. Authenticated routes remain locked
    # to the configured BACKEND_CORS_ORIGINS list.
    PUBLIC_PREFIX = f"{settings.API_V1_STR}/public"

    @application.middleware("http")
    async def public_cors_middleware(request: Request, call_next):
        """
        Inject permissive CORS headers for public widget routes BEFORE the
        global CORSMiddleware runs, so any origin can call them.
        """
        if request.headers.get("upgrade", "").lower() == "websocket":
            return await call_next(request)

        is_public = request.url.path.startswith(PUBLIC_PREFIX)
        origin = request.headers.get("origin", "")

        if is_public and request.method == "OPTIONS":
            from fastapi.responses import Response as FastAPIResponse
            return FastAPIResponse(
                status_code=204,
                headers={
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
                    "Access-Control-Allow-Headers": "Content-Type, Authorization",
                    "Access-Control-Max-Age": "86400",
                },
            )

        response = await call_next(request)

        if is_public and origin:
            response.headers["Access-Control-Allow-Origin"] = "*"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
            response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"

        return response

    # Restricted CORS for all other routes (dashboard, auth, admin)
    if settings.BACKEND_CORS_ORIGINS:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=[str(origin).strip("/") for origin in settings.BACKEND_CORS_ORIGINS],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    # Security Headers Middleware
    @application.middleware("http")
    async def add_security_headers(request: Request, call_next):
        if request.headers.get("upgrade", "").lower() == "websocket":
            return await call_next(request)
        response = await call_next(request)
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        
        # Standard content security policy allowing application self resources,
        # secure WebSockets, data/blob image sources, and jsdelivr CDN for API docs (Swagger)
        csp_directives = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "img-src 'self' data: blob: https://cdn.jsdelivr.net; "
            "connect-src 'self' ws: wss:;"
        )
        response.headers["Content-Security-Policy"] = csp_directives
        return response

    # Request Logging Middleware
    @application.middleware("http")
    async def log_requests(request: Request, call_next):
        if request.headers.get("upgrade", "").lower() == "websocket":
            return await call_next(request)
        start_time = time.time()
        client_host = request.client.host if request.client else "unknown"
        
        # Log request receipt
        logger.info(f"Incoming: {request.method} {request.url.path} from {client_host}")
        
        try:
            response = await call_next(request)
            process_time = (time.time() - start_time) * 1000
            
            # Log response details
            logger.info(
                f"Outgoing: {request.method} {request.url.path} - Status: {response.status_code} - Completed in {process_time:.2f}ms"
            )
            return response
        except Exception as e:
            process_time = (time.time() - start_time) * 1000
            logger.error(
                f"Failure: {request.method} {request.url.path} - Raised Exception: {str(e)} - Completed in {process_time:.2f}ms",
                exc_info=True
            )
            raise

    # Include api router
    application.include_router(api_router, prefix=settings.API_V1_STR)

    @application.get("/", include_in_schema=False)
    def redirect_to_docs():
        """
        Redirect root path to interactive Swagger documentation.
        """
        return RedirectResponse(url="/docs")

    @application.get("/health", tags=["health"])
    async def health_check(
        db: Session = Depends(get_db),
        redis_conn: Any = Depends(get_redis)
    ):
        """
        Verify backend service, database, and cache (Redis) health.
        """
        health_status = {
            "status": "healthy",
            "database": "untested",
            "redis": "untested"
        }
        
        # Test Database Connection
        try:
            db.execute(text("SELECT 1"))
            health_status["database"] = "healthy"
        except Exception as e:
            health_status["status"] = "unhealthy"
            health_status["database"] = f"unhealthy: {str(e)}"

        # Test Redis Connection
        try:
            await redis_conn.ping()
            if getattr(redis_conn, "is_mock", False):
                health_status["redis"] = "healthy (mocked)"
            else:
                health_status["redis"] = "healthy"
        except Exception as e:
            health_status["status"] = "unhealthy"
            health_status["redis"] = f"unhealthy: {str(e)}"

        return health_status

    return application

app = get_application()
