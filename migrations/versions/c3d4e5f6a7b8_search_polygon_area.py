"""search polygon area

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-11-06 23:45:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "c3d4e5f6a7b8"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("search_jobs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("polygon", sa.JSON(), nullable=True))


def downgrade():
    with op.batch_alter_table("search_jobs", schema=None) as batch_op:
        batch_op.drop_column("polygon")
