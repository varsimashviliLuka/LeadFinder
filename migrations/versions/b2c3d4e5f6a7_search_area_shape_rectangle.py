"""search area shape rectangle

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-11-06 23:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "b2c3d4e5f6a7"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("search_jobs", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("area_shape", sa.String(length=16), nullable=False, server_default="circle")
        )
        batch_op.add_column(sa.Column("south", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("west", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("north", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("east", sa.Float(), nullable=True))


def downgrade():
    with op.batch_alter_table("search_jobs", schema=None) as batch_op:
        batch_op.drop_column("east")
        batch_op.drop_column("north")
        batch_op.drop_column("west")
        batch_op.drop_column("south")
        batch_op.drop_column("area_shape")
