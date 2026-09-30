#!/usr/bin/env python3
"""
Configuration Validation Script
Validates backend/.env configuration before deployment
Usage: python validate_config.py
"""
import sys
import os
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent))


def print_section(title):
    """Print section header"""
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print('=' * 60)


def check_mark(passed):
    """Return check mark or X based on status"""
    return "PASS" if passed else "FAIL"


def validate_configuration():
    """Validate configuration and report issues"""
    issues = []
    warnings = []

    print_section("HLD Generator Configuration Validation")

    # Load configuration
    print("\n1. Loading configuration...")
    try:
        from config import settings
        print(f"   [{check_mark(True)}] Configuration loaded successfully")
    except Exception as e:
        print(f"   [{check_mark(False)}] Failed to load configuration: {e}")
        return False

    # Check CORS configuration
    print("\n2. Checking CORS configuration...")
    try:
        cors_origins = settings.CORS_ORIGINS
        if isinstance(cors_origins, list):
            print(f"   [{check_mark(True)}] CORS_ORIGINS is a list with {len(cors_origins)} origins")

            # Check for localhost-only in production
            if settings.ENVIRONMENT.lower() in ['production', 'prod']:
                all_localhost = all('localhost' in origin or '127.0.0.1' in origin
                                   for origin in cors_origins)
                if all_localhost:
                    warnings.append(
                        "CORS_ORIGINS contains only localhost URLs in production environment. "
                        "Frontend will not be accessible via public IP or domain."
                    )
                    print(f"   [{check_mark(False)}] WARNING: All origins are localhost in production")

            # Display origins
            for origin in cors_origins:
                print(f"       - {origin}")
        else:
            issues.append(f"CORS_ORIGINS is not a list: {type(cors_origins)}")
            print(f"   [{check_mark(False)}] CORS_ORIGINS must be a list")
    except Exception as e:
        issues.append(f"Error checking CORS: {e}")
        print(f"   [{check_mark(False)}] Error: {e}")

    # Check secrets
    print("\n3. Checking security configuration...")

    # JWT Secret
    try:
        jwt_secret = settings.JWT_SECRET_KEY
        if len(jwt_secret) < 32:
            issues.append("JWT_SECRET_KEY is too short (minimum 32 characters)")
            print(f"   [{check_mark(False)}] JWT_SECRET_KEY too short: {len(jwt_secret)} chars (min 32)")
        else:
            print(f"   [{check_mark(True)}] JWT_SECRET_KEY length: {len(jwt_secret)} chars")

        # Check for common insecure values
        insecure_values = ['changeme', 'secret', 'password', 'test', 'REPLACE_WITH']
        if any(val.lower() in jwt_secret.lower() for val in insecure_values):
            issues.append("JWT_SECRET_KEY appears to be a placeholder/insecure value")
            print(f"   [{check_mark(False)}] JWT_SECRET_KEY appears to be a placeholder")
    except Exception as e:
        issues.append(f"Error checking JWT_SECRET_KEY: {e}")
        print(f"   [{check_mark(False)}] Error: {e}")

    # Encryption Key
    try:
        import base64
        enc_key = settings.ENCRYPTION_KEY
        decoded = base64.urlsafe_b64decode(enc_key)
        if len(decoded) == 32:
            print(f"   [{check_mark(True)}] ENCRYPTION_KEY is valid (32 bytes)")
        else:
            issues.append(f"ENCRYPTION_KEY is {len(decoded)} bytes, should be 32")
            print(f"   [{check_mark(False)}] ENCRYPTION_KEY invalid length: {len(decoded)} bytes")
    except Exception as e:
        issues.append(f"ENCRYPTION_KEY is not valid base64: {e}")
        print(f"   [{check_mark(False)}] ENCRYPTION_KEY invalid: {e}")

    # Check database configuration
    print("\n4. Checking database configuration...")
    try:
        db_url = settings.DATABASE_URL
        is_sqlite = db_url.startswith("sqlite")
        is_production = settings.ENVIRONMENT.lower() in ['production', 'prod']

        if is_sqlite:
            print(f"   [{check_mark(not is_production)}] Using SQLite database")
            if is_production:
                warnings.append(
                    "Using SQLite in production. This is NOT recommended for 10+ concurrent users. "
                    "Migrate to PostgreSQL for production deployment."
                )
                print(f"   [{check_mark(False)}] WARNING: SQLite not recommended for production")
        else:
            print(f"   [{check_mark(True)}] Using PostgreSQL database")
            print(f"       Pool size: {settings.DATABASE_POOL_SIZE}")
            print(f"       Max overflow: {settings.DATABASE_MAX_OVERFLOW}")
    except Exception as e:
        issues.append(f"Error checking database: {e}")
        print(f"   [{check_mark(False)}] Error: {e}")

    # Check concurrency settings
    print("\n5. Checking concurrency settings...")
    try:
        print(f"   [{check_mark(True)}] API workers: {settings.WORKERS}")
        print(f"   [{check_mark(True)}] Celery concurrency: {settings.CELERY_WORKER_CONCURRENCY}")
        print(f"   [{check_mark(True)}] Max concurrent jobs per user: {settings.MAX_CONCURRENT_JOBS_PER_USER}")
        print(f"   [{check_mark(True)}] Total concurrent jobs (tenant): {settings.DEFAULT_TENANT_MAX_CONCURRENT_JOBS}")

        if settings.CELERY_WORKER_CONCURRENCY < 10:
            warnings.append(
                f"CELERY_WORKER_CONCURRENCY is {settings.CELERY_WORKER_CONCURRENCY}. "
                "For 10+ concurrent users, set this to at least 10."
            )
    except Exception as e:
        issues.append(f"Error checking concurrency: {e}")
        print(f"   [{check_mark(False)}] Error: {e}")

    # Check JWT expiration
    print("\n6. Checking JWT token expiration...")
    try:
        jwt_expiry = settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES
        print(f"   [{check_mark(True)}] JWT access token expiration: {jwt_expiry} minutes")

        if jwt_expiry < 60:
            warnings.append(
                f"JWT access tokens expire after {jwt_expiry} minutes. "
                "HLD generation can take 1+ hour. Users may get logged out mid-job. "
                "Consider increasing to 120+ minutes."
            )
            print(f"   [{check_mark(False)}] WARNING: JWT expiry may be too short for long jobs")
    except Exception as e:
        issues.append(f"Error checking JWT expiration: {e}")
        print(f"   [{check_mark(False)}] Error: {e}")

    # Check OCI configuration
    print("\n7. Checking OCI configuration...")
    try:
        if settings.OCI_COMPARTMENT_ID:
            if 'ocid1.compartment' in settings.OCI_COMPARTMENT_ID:
                if 'your-compartment' in settings.OCI_COMPARTMENT_ID.lower():
                    issues.append("OCI_COMPARTMENT_ID appears to be a placeholder")
                    print(f"   [{check_mark(False)}] OCI_COMPARTMENT_ID is a placeholder")
                else:
                    print(f"   [{check_mark(True)}] OCI_COMPARTMENT_ID is configured")
            else:
                issues.append("OCI_COMPARTMENT_ID format invalid")
                print(f"   [{check_mark(False)}] OCI_COMPARTMENT_ID format invalid")
        else:
            issues.append("OCI_COMPARTMENT_ID not set")
            print(f"   [{check_mark(False)}] OCI_COMPARTMENT_ID not configured")

        # Check model IDs
        if settings.OCI_GENAI_MODEL_ID:
            if 'your-model' in settings.OCI_GENAI_MODEL_ID.lower():
                issues.append("OCI_GENAI_MODEL_ID is a placeholder")
                print(f"   [{check_mark(False)}] OCI_GENAI_MODEL_ID is a placeholder")
            else:
                print(f"   [{check_mark(True)}] OCI_GENAI_MODEL_ID is configured")
        else:
            issues.append("OCI_GENAI_MODEL_ID not set")
            print(f"   [{check_mark(False)}] OCI_GENAI_MODEL_ID not configured")
    except Exception as e:
        issues.append(f"Error checking OCI config: {e}")
        print(f"   [{check_mark(False)}] Error: {e}")

    # Check file paths
    print("\n8. Checking file storage paths...")
    try:
        paths_to_check = {
            'STORAGE_PATH': settings.STORAGE_PATH,
            'IMAGE_STORAGE_DIR': settings.IMAGE_STORAGE_DIR,
            'OUTPUT_DIR': settings.OUTPUT_DIR,
            'RAG_WORKING_DIR': settings.RAG_WORKING_DIR,
        }

        for path_name, path_value in paths_to_check.items():
            path_obj = Path(path_value)
            if path_obj.is_absolute():
                print(f"   [{check_mark(True)}] {path_name}: {path_value}")
            else:
                warnings.append(f"{path_name} is relative: {path_value}")
                print(f"   [{check_mark(False)}] WARNING: {path_name} is relative")

            # Check if path exists/writable
            try:
                path_obj.mkdir(parents=True, exist_ok=True)
                test_file = path_obj / '.write_test'
                test_file.write_text('test')
                test_file.unlink()
                print(f"       - Path exists and writable")
            except Exception as e:
                warnings.append(f"{path_name} not writable: {e}")
                print(f"       - WARNING: Not writable: {e}")
    except Exception as e:
        issues.append(f"Error checking paths: {e}")
        print(f"   [{check_mark(False)}] Error: {e}")

    # Print summary
    print_section("Validation Summary")

    if issues:
        print(f"\n  CRITICAL ISSUES ({len(issues)}):")
        for i, issue in enumerate(issues, 1):
            print(f"    {i}. {issue}")

    if warnings:
        print(f"\n  WARNINGS ({len(warnings)}):")
        for i, warning in enumerate(warnings, 1):
            print(f"    {i}. {warning}")

    if not issues and not warnings:
        print("\n  All checks passed! Configuration looks good.")
        print_section("Next Steps")
        print("  1. Start backend: python main.py")
        print("  2. Start Celery worker: celery -A celery_app worker --loglevel=info")
        print("  3. Check health: curl http://localhost:6602/health/detailed")
        print("  4. Deploy to production (see PRODUCTION_DEPLOYMENT_GUIDE.md)")
        return True
    elif not issues:
        print("\n  Configuration is valid but has warnings. Review warnings above.")
        return True
    else:
        print(f"\n  Configuration has {len(issues)} critical issues. Please fix before deployment.")
        print("\n  See QUICK_START_ENV_CONFIGURATION.md for configuration guide.")
        return False


if __name__ == "__main__":
    success = validate_configuration()
    sys.exit(0 if success else 1)
