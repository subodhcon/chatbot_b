"""drop session and ingestion tracking metadata tables

Revision ID: 8f1f97b5c641
Revises: a07ec767df94
Create Date: 2026-07-11 11:42:21.231541

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8f1f97b5c641'
down_revision: Union[str, None] = 'a07ec767df94'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop tables with cascade to clean up all constraints
    op.execute("DROP TABLE IF EXISTS ingestion_jobs CASCADE")
    op.execute("DROP TABLE IF EXISTS url_crawls CASCADE")
    op.execute("DROP TABLE IF EXISTS knowledge_sources CASCADE")
    op.execute("DROP TABLE IF EXISTS documents CASCADE")
    op.execute("DROP TABLE IF EXISTS export_jobs CASCADE")
    op.execute("DROP TABLE IF EXISTS analytics_events CASCADE")
    op.execute("DROP TABLE IF EXISTS feedback_ratings CASCADE")
    op.execute("DROP TABLE IF EXISTS conversations CASCADE")
    op.execute("DROP TABLE IF EXISTS widget_sessions CASCADE")


def downgrade() -> None:
    pass
