"""Rename the job's product planning JSON field.

Revision ID: 20260927profile
Revises: 42156fd6dcfa
"""

from alembic import op


revision = "20260927profile"
down_revision = "42156fd6dcfa"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("jobs", "product_kb_path", new_column_name="product_profile_file")


def downgrade() -> None:
    op.alter_column("jobs", "product_profile_file", new_column_name="product_kb_path")
