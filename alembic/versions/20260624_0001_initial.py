"""Initial Grid++ platform schema.

Revision ID: 20260624_0001
Revises:
Create Date: 2026-06-24
"""

from alembic import op
import sqlalchemy as sa


revision = "20260624_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("email"),
    )
    op.create_table(
        "sprites",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("tags", sa.Text(), nullable=False, server_default=""),
        sa.Column("image_data", sa.LargeBinary(), nullable=False),
        sa.Column(
            "owner_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("length(image_data) = 4096", name="ck_sprites_image_data_length"),
    )
    op.create_index("idx_sprites_created_at", "sprites", ["created_at"])
    op.create_index("idx_sprites_owner_id", "sprites", ["owner_id"])
    op.create_table(
        "packs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "owner_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("idx_packs_owner_id", "packs", ["owner_id"])
    op.create_table(
        "pack_sprites",
        sa.Column(
            "pack_id",
            sa.Integer(),
            sa.ForeignKey("packs.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "sprite_id",
            sa.Integer(),
            sa.ForeignKey("sprites.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), primary_key=True),
        sa.CheckConstraint("position >= 0", name="ck_pack_sprites_position_nonnegative"),
        sa.UniqueConstraint("pack_id", "sprite_id", name="uq_pack_sprites_pack_sprite"),
    )
    op.create_index("idx_pack_sprites_sprite_id", "pack_sprites", ["sprite_id"])


def downgrade() -> None:
    op.drop_index("idx_pack_sprites_sprite_id", table_name="pack_sprites")
    op.drop_table("pack_sprites")
    op.drop_index("idx_packs_owner_id", table_name="packs")
    op.drop_table("packs")
    op.drop_index("idx_sprites_owner_id", table_name="sprites")
    op.drop_index("idx_sprites_created_at", table_name="sprites")
    op.drop_table("sprites")
    op.drop_table("users")
