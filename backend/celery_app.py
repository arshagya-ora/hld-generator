"""
Celery Application Configuration
Async job queue for HLD generation
"""
# Load environment variables FIRST before any other imports
from pathlib import Path
from dotenv import load_dotenv

# Find and load .env file
_env_file = Path(__file__).parent / ".env"
if _env_file.exists():
    load_dotenv(_env_file, override=False)

import sys
import logging
from celery import Celery
from celery.signals import worker_process_init
from config import settings

logger = logging.getLogger(__name__)

# Create Celery app
celery_app = Celery(
    "hld_generator",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=["tasks.hld_generation"]  # Auto-discover tasks
)

# Celery configuration
celery_app.conf.update(
    # Task settings
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,

    # Task execution
    task_track_started=True,
    task_time_limit=settings.CELERY_TASK_TIME_LIMIT,
    task_soft_time_limit=settings.CELERY_TASK_SOFT_TIME_LIMIT,

    # Result backend
    result_expires=3600 * 24,  # 24 hours

    # Worker settings
    worker_concurrency=settings.CELERY_WORKER_CONCURRENCY,  # concurrent task executions
    worker_prefetch_multiplier=settings.CELERY_WORKER_PREFETCH_MULTIPLIER,  # One task per worker
    worker_max_tasks_per_child=settings.CELERY_WORKER_MAX_TASKS_PER_CHILD,  # Restart after N tasks
    worker_max_memory_per_child=1024 * 1024 * 500,  # Restart if worker exceeds 500MB (prevent memory leaks)

    # Retry settings
    task_acks_late=True,  # Acknowledge task after completion
    task_reject_on_worker_lost=True,

    # Performance
    broker_connection_retry_on_startup=True,  # Retry on startup (Redis may start slightly after Celery)
    broker_connection_retry=True,  # Retry connections on transient failures
    broker_connection_max_retries=10,  # Retry up to 10 times before giving up

    # Windows: billiard prefork pool is broken (handle/permission errors in spawn workers)
    # Use 'solo' pool on Windows — runs tasks sequentially in the main process
    # IMPORTANT: 'solo' pool IGNORES worker_concurrency — only 1 job at a time on Windows.
    # For concurrent jobs, use a pool and worker count appropriate to the deployment.
    # Alternative for Windows dev: run multiple `celery worker` processes instead of
    # relying on concurrency within a single worker.
    **({"worker_pool": "solo"} if sys.platform == "win32" else {}),
)

# Task routes (optional - for multiple queues)
celery_app.conf.task_routes = {
    "tasks.hld_generation.*": {"queue": "hld_generation"},
    "tasks.notifications.*": {"queue": "notifications"},
}

# Default queues the worker listens on (so -Q flag isn't required)
from kombu import Queue
celery_app.conf.task_queues = [
    Queue("celery"),
    Queue("hld_generation"),
]

if sys.platform == "win32":
    import logging as _log
    _log.getLogger(__name__).warning(
        "Celery is running with 'solo' pool on Windows. "
        "Only 1 job will run at a time regardless of worker_concurrency=%d. "
        "For concurrent job processing, deploy on Linux or start multiple worker processes.",
        settings.CELERY_WORKER_CONCURRENCY,
    )

# ============================================================================
# CELERY BEAT SCHEDULE - Periodic Tasks
# ============================================================================
# To run periodic tasks, start the Celery beat scheduler:
#   celery -A backend.celery_app beat --loglevel=info
# ============================================================================

from celery.schedules import crontab

celery_app.conf.beat_schedule = {
    'cleanup-old-jobs-daily': {
        'task': 'tasks.hld_generation.cleanup_old_jobs',
        'schedule': crontab(hour=2, minute=0),  # Run at 2:00 AM UTC daily
        'args': (30,),  # Delete jobs older than 30 days (configurable in settings)
        'options': {
            'expires': 3600,  # Task expires after 1 hour if not picked up
        }
    },
}

# Timezone for beat scheduler (should match celery_app timezone)
celery_app.conf.timezone = 'UTC'


# ============================================================================
# WORKER INITIALIZATION - OCI Services
# ============================================================================
@worker_process_init.connect
def init_worker_process(**kwargs):
    """
    Initialize OCI services when Celery worker process starts.

    This runs once per worker process (not per task).
    Critical because OCI adapters need to be initialized before tasks run.
    """
    logger.info("Initializing OCI services for Celery worker...")
    try:
        from services.oci_client import initialize_oci_services
        initialize_oci_services()
        logger.info("✅ OCI services initialized successfully in worker process")
    except Exception as e:
        logger.error(f"❌ Failed to initialize OCI services in worker: {e}")
        logger.error("Tasks will fail until OCI services are properly configured")
        raise


if __name__ == "__main__":
    celery_app.start()
