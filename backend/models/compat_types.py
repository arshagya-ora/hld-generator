"""
Cross-database compatible column types.
Maps PostgreSQL-specific types (UUID, JSONB, INET, ARRAY) to
SQLite-friendly equivalents so the same models work on both backends.
"""
from sqlalchemy import String, Text, TypeDecorator, JSON
from sqlalchemy.dialects import postgresql
import json
import uuid


# ---------------------------------------------------------------------------
# UUID  – stored as CHAR(36) on SQLite, native UUID on PostgreSQL
# ---------------------------------------------------------------------------
class GUID(TypeDecorator):
    """Platform-independent UUID type."""
    impl = String(36)
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(postgresql.UUID(as_uuid=True))
        return dialect.type_descriptor(String(36))

    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        if dialect.name == "postgresql":
            return value
        return str(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return value
        if not isinstance(value, uuid.UUID):
            return uuid.UUID(value)
        return value


# Alias so models can use UUID-like semantics
UUID = GUID


# ---------------------------------------------------------------------------
# JSONB  – falls back to JSON (stored as TEXT) on SQLite
# ---------------------------------------------------------------------------
class JSONB(TypeDecorator):
    """Platform-independent JSONB type."""
    impl = Text
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(postgresql.JSONB)
        return dialect.type_descriptor(JSON)

    def process_bind_param(self, value, dialect):
        if value is not None and dialect.name != "postgresql":
            return json.dumps(value) if not isinstance(value, str) else value
        return value

    def process_result_value(self, value, dialect):
        if value is not None and isinstance(value, str) and dialect.name != "postgresql":
            try:
                return json.loads(value)
            except (json.JSONDecodeError, TypeError):
                return value
        return value


# ---------------------------------------------------------------------------
# INET  – stored as plain String on SQLite
# ---------------------------------------------------------------------------
class INET(TypeDecorator):
    """Platform-independent INET type for IP addresses."""
    impl = String(45)   # longest IPv6 representation
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(postgresql.INET)
        return dialect.type_descriptor(String(45))


# ---------------------------------------------------------------------------
# ARRAY  – stored as JSON list on SQLite
# ---------------------------------------------------------------------------
class ARRAY(TypeDecorator):
    """Platform-independent ARRAY type (stored as JSON on non-PG)."""
    impl = Text
    cache_ok = True

    def __init__(self, item_type=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.item_type = item_type

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(postgresql.ARRAY(String))
        return dialect.type_descriptor(JSON)

    def process_bind_param(self, value, dialect):
        if value is not None and dialect.name != "postgresql":
            return json.dumps(value) if not isinstance(value, str) else value
        return value

    def process_result_value(self, value, dialect):
        if value is not None and isinstance(value, str) and dialect.name != "postgresql":
            try:
                return json.loads(value)
            except (json.JSONDecodeError, TypeError):
                return value
        return value
