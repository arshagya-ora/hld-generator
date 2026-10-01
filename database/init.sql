-- PostgreSQL Initialization Script for ArchDraft
-- This script is referenced in docker-compose.yml but can be removed if using Alembic only

-- Create extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";  -- For text search performance

-- Create custom types
DO $$ BEGIN
    CREATE TYPE job_status AS ENUM (
        'pending',
        'document_analysis',
        'blueprint_generation',
        'content_generation',
        'assembly',
        'completed',
        'failed',
        'cancelled'
    );
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

-- Create indexes for performance (Alembic creates tables, this adds extra indexes)
-- Note: These will run AFTER Alembic creates tables

-- Performance indexes for common queries
CREATE INDEX IF NOT EXISTS idx_users_email_lower ON users(LOWER(email));
CREATE INDEX IF NOT EXISTS idx_users_tenant_id ON users(tenant_id);
CREATE INDEX IF NOT EXISTS idx_users_is_active ON users(is_active) WHERE is_active = true;

CREATE INDEX IF NOT EXISTS idx_jobs_created_by ON jobs(created_by_id);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_tenant_id ON jobs(tenant_id);
CREATE INDEX IF NOT EXISTS idx_jobs_created_at_desc ON jobs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_composite ON jobs(tenant_id, status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_documents_uploaded_by ON documents(uploaded_by_id);
CREATE INDEX IF NOT EXISTS idx_documents_tenant_id ON documents(tenant_id);

CREATE INDEX IF NOT EXISTS idx_api_keys_key_hash ON api_keys(key_hash);
CREATE INDEX IF NOT EXISTS idx_api_keys_user_id ON api_keys(user_id);
CREATE INDEX IF NOT EXISTS idx_api_keys_is_active ON api_keys(is_active) WHERE is_active = true;

CREATE INDEX IF NOT EXISTS idx_audit_logs_user_id ON audit_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_tenant_id ON audit_logs(tenant_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_timestamp ON audit_logs(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_audit_logs_action ON audit_logs(action);

-- Full-text search indexes
CREATE INDEX IF NOT EXISTS idx_jobs_fts ON jobs USING gin(to_tsvector('english', job_name));

-- Set database parameters for performance
ALTER DATABASE hld_generator SET timezone TO 'UTC';
ALTER DATABASE hld_generator SET client_encoding TO 'UTF8';
ALTER DATABASE hld_generator SET default_transaction_isolation TO 'read committed';

-- Create a function for updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Note: Alembic will create the actual tables
-- This file only provides additional optimizations and extensions
