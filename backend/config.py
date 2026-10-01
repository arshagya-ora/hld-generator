"""
Backend Configuration
Loads environment variables and provides configuration settings
"""
from pathlib import Path
from pydantic_settings import BaseSettings
from pydantic import field_validator, ValidationError
from typing import Optional, Union
from functools import lru_cache
import sys
import secrets
import base64

# Compute project root once (backend/ is one level below project root)
_BACKEND_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _BACKEND_DIR.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""

    # Application
    APP_NAME: str = "ArchDraft API"
    APP_VERSION: str = "1.0.0"
    ENVIRONMENT: str = "development"
    DEBUG: bool = False

    # Server
    HOST: str = "127.0.0.1"
    PORT: int = 8000
    WORKERS: int = 1  # FastAPI workers (Set to 1 for Windows stability)

    # Database (defaults to SQLite for local dev; override in .env for PostgreSQL)
    DATABASE_URL: str = "sqlite+aiosqlite:///./hld_generator.db"
    DATABASE_POOL_SIZE: int = 5
    DATABASE_MAX_OVERFLOW: int = 10
    DATABASE_POOL_TIMEOUT: int = 30
    DATABASE_POOL_RECYCLE: int = 1800

    # Redis
    REDIS_URL: str = "redis://localhost:6379"
    REDIS_DB: int = 0
    REDIS_CACHE_DB: int = 1
    REDIS_CELERY_BROKER_DB: int = 2
    REDIS_CELERY_BACKEND_DB: int = 3

    # Celery
    CELERY_BROKER_URL: str = "redis://localhost:6379/2"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/3"
    CELERY_TASK_TIME_LIMIT: int = 3600  # 1 hour
    CELERY_TASK_SOFT_TIME_LIMIT: int = 3300  # 55 minutes
    CELERY_WORKER_CONCURRENCY: int = 10  # Configured Celery worker concurrency
    CELERY_WORKER_PREFETCH_MULTIPLIER: int = 1  # One task per worker
    CELERY_WORKER_MAX_TASKS_PER_CHILD: int = 10  # Restart after 10 tasks (prevent memory leaks)

    # JWT Authentication
    # SECURITY: These MUST be set via environment variables in production
    # Generate JWT_SECRET_KEY: python -c "import secrets; print(secrets.token_urlsafe(32))"
    # Generate ENCRYPTION_KEY: python -c "import secrets, base64; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"
    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    # JWT Token Expiration
    # PRODUCTION: Set to 60+ minutes for long-running HLD generation jobs (can take 1+ hour)
    # Access tokens expire during job execution → user gets logged out → bad UX
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 120  # 2 hours (allows for 1-hour HLD generation)
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Security
    # SECURITY: ENCRYPTION_KEY MUST be set via environment variables in production
    ENCRYPTION_KEY: str
    BCRYPT_ROUNDS: int = 12

    @field_validator('JWT_SECRET_KEY')
    @classmethod
    def validate_jwt_secret(cls, v: str) -> str:
        """Validate JWT_SECRET_KEY is not a placeholder"""
        forbidden_values = [
            'your-secret-key-change-in-production',
            'changeme',
            'secret',
            'password',
            'test',
        ]
        if v.lower() in forbidden_values:
            raise ValueError(
                'JWT_SECRET_KEY is insecure placeholder. '
                'Generate a secure key: python -c "import secrets; print(secrets.token_urlsafe(32))"'
            )
        if len(v) < 32:
            raise ValueError('JWT_SECRET_KEY must be at least 32 characters long')
        return v

    @field_validator('ENCRYPTION_KEY')
    @classmethod
    def validate_encryption_key(cls, v: str) -> str:
        """Validate ENCRYPTION_KEY is not a placeholder and is proper base64"""
        forbidden_values = [
            'your-32-byte-base64-encryption-key',
            'changeme',
            'secret',
        ]
        if v.lower() in forbidden_values:
            raise ValueError(
                'ENCRYPTION_KEY is insecure placeholder. '
                'Generate: python -c "import secrets, base64; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"'
            )
        # Validate it's proper base64 and 32 bytes when decoded
        try:
            decoded = base64.urlsafe_b64decode(v)
            if len(decoded) != 32:
                raise ValueError('ENCRYPTION_KEY must be base64-encoded 32 bytes')
        except Exception as e:
            raise ValueError(f'ENCRYPTION_KEY must be valid base64: {e}')
        return v

    @field_validator('DEBUG')
    @classmethod
    def validate_debug_mode(cls, v: bool) -> bool:
        """Warn if DEBUG mode is enabled"""
        if v:
            import os
            env = os.getenv('ENVIRONMENT', 'development')
            if env.lower() in ['production', 'prod']:
                raise ValueError(
                    'DEBUG mode MUST NOT be enabled in production. '
                    'Set DEBUG=false in your .env file.'
                )
            print('\nWARNING: DEBUG mode is enabled. This should ONLY be used in development.\n')
        return v

    # File Upload
    MAX_UPLOAD_SIZE_MB: int = 20
    MAX_UPLOAD_FILES: int = 10

    @field_validator('MAX_UPLOAD_SIZE_MB', 'MAX_UPLOAD_FILES')
    @classmethod
    def validate_upload_limits(cls, v: int) -> int:
        if v < 1:
            raise ValueError('Upload limits must be positive')
        return v
    ALLOWED_MIME_TYPES: list = [
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",  # DOCX
        "application/pdf"
    ]
    # File Storage Paths
    # PRODUCTION: Use absolute paths or mount persistent volumes
    # Docker: /app/storage, /app/images, /app/outputs, /app/rag_storage
    # Native: /var/lib/hld-generator/storage, /var/lib/hld-generator/images, etc.
    STORAGE_PATH: str = "./storage"
    IMAGE_STORAGE_DIR: str = "./images"
    OUTPUT_DIR: str = "./outputs"
    RAG_WORKING_DIR: str = "../rag_storage"

    @field_validator('STORAGE_PATH', 'IMAGE_STORAGE_DIR', 'OUTPUT_DIR', 'RAG_WORKING_DIR')
    @classmethod
    def resolve_storage_paths(cls, v: str) -> str:
        """Convert relative paths to absolute paths based on backend directory"""
        from pathlib import Path
        import os
        path = Path(v)
        if not path.is_absolute():
            # Resolve relative to backend directory (where .env is)
            backend_dir = Path(__file__).parent
            path = (backend_dir / path).resolve()
        # Create directory if it doesn't exist
        path.mkdir(parents=True, exist_ok=True)
        return str(path)

    # Rate Limiting
    RATE_LIMIT_PER_MINUTE: int = 60
    RATE_LIMIT_JOBS_PER_HOUR: int = 20
    MAX_CONCURRENT_JOBS_PER_USER: int = 5

    # CORS
    # PRODUCTION: Set to your actual domain(s) via environment variable
    # Example: CORS_ORIGINS=["https://hld.yourdomain.com","https://api.yourdomain.com"]
    # Development: CORS_ORIGINS=["http://localhost:6601","http://localhost:5173"]
    # Can be provided as JSON string or Python list
    CORS_ORIGINS: Union[str, list] = '["http://localhost:3000","http://localhost:5173"]'
    CORS_ALLOW_CREDENTIALS: bool = True

    @field_validator('CORS_ORIGINS', mode='before')
    @classmethod
    def parse_cors_origins(cls, v) -> list:
        """Parse CORS_ORIGINS from JSON string or list to validated list"""
        # If already a list (from Python evaluation in .env), validate and return
        if isinstance(v, list):
            for origin in v:
                if not isinstance(origin, str):
                    raise ValueError("Each CORS origin must be a string")
                # Allow wildcard or validate URL format
                if origin != "*" and not (origin.startswith("http://") or origin.startswith("https://")):
                    raise ValueError(f"Invalid CORS origin: {origin}. Must start with http:// or https://")
            return v

        # If string, parse as JSON
        if isinstance(v, str):
            import json
            try:
                parsed = json.loads(v)
                if not isinstance(parsed, list):
                    raise ValueError("CORS_ORIGINS must be a JSON array")
                # Validate each origin
                for origin in parsed:
                    if not isinstance(origin, str):
                        raise ValueError("Each CORS origin must be a string")
                    # Allow wildcard or validate URL format
                    if origin != "*" and not (origin.startswith("http://") or origin.startswith("https://")):
                        raise ValueError(f"Invalid CORS origin: {origin}. Must start with http:// or https://")
                return parsed
            except json.JSONDecodeError as e:
                raise ValueError(f"CORS_ORIGINS must be valid JSON array: {e}")

        raise ValueError("CORS_ORIGINS must be a JSON string or list")

    # Multi-tenancy
    DEFAULT_TENANT_MAX_USERS: int = 10
    DEFAULT_TENANT_MAX_CONCURRENT_JOBS: int = 10  # Default tenant concurrency limit

    # Job Configuration
    JOB_RETENTION_DAYS: int = 30
    DOCUMENT_RETENTION_DAYS: int = 90

    # Logging Configuration
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "json"

    # ArchDraft paths (absolute, resolved from project structure)
    HLD_GENERATOR_PATH: str = str(_PROJECT_ROOT)
    PRODUCT_PROFILE_DIR: str = str(_PROJECT_ROOT / "product_profiles")

    # OCI Configuration
    OCI_PROFILE: str = "CONFIG"
    OCI_OPENAI_PROFILE: str = "CONFIG"
    OCI_CONFIG_FILE: str = "~/.oci/config"
    OCI_OPENAI_CONFIG_FILE: str = "~/.oci/config"
    OCI_COMPARTMENT_ID: Optional[str] = None
    OCI_OPENAI_COMPARTMENT_ID: Optional[str] = None

    OCI_BASE_URL: str = ""
    OCI_OPENAI_ENDPOINT: str = ""
    OCI_GENAI_ENDPOINT: str = ""

    OCI_GENAI_MODEL_ID: Optional[str] = None
    OCI_CHAT_MODEL_ID: Optional[str] = None
    VISION_MODEL_ID: Optional[str] = None
    OCI_EMBED_MODEL_ID: str = "openai.text-embedding-3-large"
    OCI_EMBEDDING_MODEL_ID: str = "openai.text-embedding-3-large"

    # LLM Provider Settings
    LLM_PROVIDER: str = "oci_openai"
    LLM_MODEL: Optional[str] = None
    LLM_ENDPOINT: str = ""
    LLM_MAX_TOKENS: int = 4096

    # Embedding Provider Settings
    EMBEDDING_PROVIDER: str = "fastembed"
    EMBEDDING_MODEL: str = "BAAI/bge-small-en-v1.5"
    EMBEDDING_DIMENSIONS: int = 384
    EMBEDDING_ENDPOINT: str = ""

    # Cognee Configuration
    COGNEE_DATA_ROOT: Optional[str] = None
    COGNEE_SYSTEM_ROOT: Optional[str] = None
    DATA_ROOT_DIRECTORY: Optional[str] = None
    SYSTEM_ROOT_DIRECTORY: Optional[str] = None

    # Feature Flags
    ENABLE_BACKEND_ACCESS_CONTROL: bool = False
    USE_LOCAL_EMBEDDINGS: bool = True
    LOCAL_EMBEDDING_MODEL: str = "BAAI/bge-small-en-v1.5"

    # Output Configuration
    OUTPUT_FORMAT: str = "markdown"
    INCLUDE_DIAGRAMS: bool = True
    VERBOSITY: str = "medium"
    REASONING_EFFORT: str = "medium"

    # Retry Configuration
    MAX_RETRIES: int = 3
    RETRY_INITIAL_DELAY: float = 1.0
    RETRY_BACKOFF_FACTOR: float = 2.0
    REQUEST_TIMEOUT: int = 240

    class Config:
        # Look for .env in both the backend/ dir (cwd) and the project root (parent)
        # so the single root .env works regardless of where the process starts
        env_file = (".env", "../.env")
        env_file_encoding = "utf-8"
        case_sensitive = True
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance"""
    return Settings()


# Export settings instance
settings = get_settings()
