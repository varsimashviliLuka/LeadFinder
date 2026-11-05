"""search nfc rating review filters

Revision ID: a1b2c3d4e5f6
Revises: 25f712881da7
Create Date: 2026-11-06 00:10:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "a1b2c3d4e5f6"
down_revision = "25f712881da7"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("search_jobs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("max_rating", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("max_reviews", sa.Integer(), nullable=True))


def downgrade():
    with op.batch_alter_table("search_jobs", schema=None) as batch_op:
        batch_op.drop_column("max_reviews")
        batch_op.drop_column("max_rating")
