"""
Main FastAPI Application
Entry point for the HLD Generator web API
"""
# Load environment variables FIRST before any other imports
from pathlib import Path
from dotenv import load_dotenv

# Find and load .env file
_env_file = Path(__file__).parent / ".env"
if _env_file.exists():
    load_dotenv(_env_file, override=False)

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
import time
import logging
from datetime import datetime, timezone

from config import settings
from api.routes import auth, documents, jobs, products

# Configure logging
logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize rate limiter
limiter = Limiter(key_func=get_remote_address)


class _UploadBodyTooLarge(Exception):
    pass


class UploadBodyLimitMiddleware:
    """Bound multipart input before FastAPI creates temporary UploadFile objects."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"] != "/api/v1/documents/upload":
            await self.app(scope, receive, send)
            return

        # Allow the configured number of files plus room for multipart headers and fields.
        max_bytes = settings.MAX_UPLOAD_SIZE_MB * settings.MAX_UPLOAD_FILES * 1024 * 1024 + 1024 * 1024
        for name, value in scope.get("headers", []):
            if name.lower() == b"content-length":
                try:
                    if int(value) > max_bytes:
                        await JSONResponse(status_code=413, content={"detail": "Upload request is too large"})(scope, receive, send)
                        return
                except ValueError:
                    pass

        received_bytes = 0

        async def limited_receive():
            nonlocal received_bytes
            message = await receive()
            if message["type"] == "http.request":
                received_bytes += len(message.get("body", b""))
                if received_bytes > max_bytes:
                    raise _UploadBodyTooLarge
            return message

        try:
            await self.app(scope, limited_receive, send)
        except _UploadBodyTooLarge:
            await JSONResponse(status_code=413, content={"detail": "Upload request is too large"})(scope, receive, send)


# Create FastAPI app
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="HLD Generator Web API",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json"
)
app.add_middleware(UploadBodyLimitMiddleware)

# Add rate limiter to app state
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=settings.CORS_ALLOW_CREDENTIALS,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Request timing middleware
@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    """Add X-Process-Time header to all responses"""
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    response.headers["X-Process-Time"] = str(process_time)
    return response


# Exception handlers
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Handle validation errors"""
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "detail": [
                {"loc": error["loc"], "msg": error["msg"], "type": error["type"]}
                for error in exc.errors()
            ],
        }
    )


# Health check endpoints
@app.get("/health", tags=["Health"])
async def health_check():
    """Basic health check endpoint"""
    return {
        "status": "healthy",
        "app_name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


@app.get("/health/detailed", tags=["Health"])
async def detailed_health_check():
    """Detailed health check including dependencies"""
    health_status = {
        "status": "healthy",
        "app_name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "dependencies": {}
    }

    # Check database connectivity
    try:
        from database import AsyncSessionLocal
        from sqlalchemy import text
        async with AsyncSessionLocal() as db:
            await db.execute(text("SELECT 1"))
        health_status["dependencies"]["database"] = {
            "status": "healthy",
            "type": "sqlite" if settings.DATABASE_URL.startswith("sqlite") else "postgresql"
        }
    except Exception as e:
        logger.warning("Database health check failed: %s", e)
        health_status["status"] = "unhealthy"
        health_status["dependencies"]["database"] = {
            "status": "unhealthy"
        }

    # Check Redis connectivity
    try:
        import redis.asyncio as redis_async
        redis_client = redis_async.from_url(settings.REDIS_URL, decode_responses=True)
        await redis_client.ping()
        await redis_client.close()
        health_status["dependencies"]["redis"] = {"status": "healthy"}
    except Exception as e:
        logger.warning("Redis health check failed: %s", e)
        health_status["status"] = "degraded"
        health_status["dependencies"]["redis"] = {
            "status": "unhealthy"
        }

    # Check Celery worker availability (check if broker is reachable)
    try:
        from celery_app import celery_app
        # Get active workers
        inspect = celery_app.control.inspect()
        active_workers = inspect.active()
        if active_workers:
            worker_count = len(active_workers)
            health_status["dependencies"]["celery"] = {
                "status": "healthy",
                "workers": worker_count
            }
        else:
            health_status["status"] = "degraded"
            health_status["dependencies"]["celery"] = {
                "status": "degraded",
                "warning": "No active workers detected"
            }
    except Exception as e:
        logger.warning("Celery health check failed: %s", e)
        health_status["status"] = "degraded"
        health_status["dependencies"]["celery"] = {
            "status": "unknown"
        }

    return health_status


# Root endpoint
@app.get("/", tags=["Root"])
async def root():
    """Root endpoint"""
    return {
        "message": "HLD Generator API",
        "version": settings.APP_VERSION,
        "docs": "/api/docs"
    }


# Include API routers
app.include_router(auth.router)
app.include_router(products.router)
app.include_router(documents.router)
app.include_router(jobs.router)


# Startup and shutdown events
@app.on_event("startup")
async def startup_event():
    """Run on application startup"""
    logger.info(f"Starting {settings.APP_NAME} v{settings.APP_VERSION}")
    logger.info(f"Database: {settings.DATABASE_URL.split('://')[0]}")

    # Auto-create database tables (especially useful for SQLite dev)
    try:
        from database import init_db
        await init_db()
        logger.info("Database tables ready")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")

    # Initialize OCI services (OCI client + Cognee)
    try:
        from services.oci_client import initialize_oci_services
        initialize_oci_services()
        logger.info("OCI services initialized")
    except Exception as e:
        logger.error(f"Failed to initialize OCI services: {e}")
        logger.error("Application will continue but HLD generation may fail")
        logger.error("Please check your .env file and ~/.oci/config")

    # Recover stale jobs from previous crashes/restarts
    # Jobs stuck in queued/running from a previous process are zombies
    try:
        from database import AsyncSessionLocal
        from sqlalchemy import select as sa_select, func as sa_func
        from models.job import Job
        from datetime import timedelta

        async with AsyncSessionLocal() as db:
            cutoff = datetime.now(timezone.utc) - timedelta(hours=2)
            result = await db.execute(
                sa_select(Job).where(
                    Job.status.in_(["queued", "running"]),
                    Job.created_at < cutoff,
                )
            )
            stale_jobs = result.scalars().all()
            if stale_jobs:
                for job in stale_jobs:
                    job.status = "failed"
                    job.error_message = "Recovered on server restart: job was stuck from previous process"
                    job.completed_at = datetime.now(timezone.utc)
                await db.commit()
                logger.warning(f"Recovered {len(stale_jobs)} stale jobs from previous process")
    except Exception as e:
        logger.warning(f"Stale job recovery failed (non-fatal): {e}")

    logger.info("=" * 60)
    logger.info("Application started successfully")
    logger.info(f"Ready to handle up to {settings.DEFAULT_TENANT_MAX_CONCURRENT_JOBS} concurrent users")
    logger.info("=" * 60)


@app.on_event("shutdown")
async def shutdown_event():
    """Run on application shutdown"""
    logger.info("Shutting down application")

    # Close database connections
    try:
        from database import engine
        await engine.dispose()
        logger.info("Database connections closed")
    except Exception as e:
        logger.error(f"Failed to close database: {e}")

    logger.info("Application shut down successfully")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
        workers=1 if settings.DEBUG else settings.WORKERS
    )
