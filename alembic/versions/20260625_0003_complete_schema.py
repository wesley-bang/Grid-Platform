"""Create the complete Grid++ platform schema.

Revision ID: 20260625_0003
Revises:
Create Date: 2026-06-25
"""

from alembic import op
import sqlalchemy as sa


revision = "20260625_0003"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create all platform tables, indexes, constraints, and triggers."""
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.Text(collation="NOCASE"), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("username", name="uq_users_username"),
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
        sa.CheckConstraint(
            "length(image_data) = 4096",
            name="ck_sprites_image_data_length",
        ),
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
        sa.CheckConstraint(
            "position >= 0",
            name="ck_pack_sprites_position_nonnegative",
        ),
        sa.UniqueConstraint(
            "pack_id",
            "sprite_id",
            name="uq_pack_sprites_pack_sprite",
        ),
    )
    op.create_index("idx_pack_sprites_sprite_id", "pack_sprites", ["sprite_id"])

    op.create_table(
        "favorite_folders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "owner_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(collation="NOCASE"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "owner_id",
            "name",
            name="uq_favorite_folders_owner_name",
        ),
    )
    op.create_index(
        "idx_favorite_folders_owner_id",
        "favorite_folders",
        ["owner_id"],
    )
    op.create_index(
        "idx_favorite_folders_created_at",
        "favorite_folders",
        ["created_at"],
    )

    op.create_table(
        "favorite_folder_sprites",
        sa.Column(
            "folder_id",
            sa.Integer(),
            sa.ForeignKey("favorite_folders.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "sprite_id",
            sa.Integer(),
            sa.ForeignKey("sprites.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "idx_favorite_folder_sprites_sprite_id",
        "favorite_folder_sprites",
        ["sprite_id"],
    )
    op.create_index(
        "idx_favorite_folder_sprites_created_at",
        "favorite_folder_sprites",
        ["created_at"],
    )

    # Enforce collection limits even for writes outside the API.
    op.execute(
        """
        CREATE TRIGGER trg_favorite_folders_limit
        BEFORE INSERT ON favorite_folders
        WHEN (SELECT COUNT(*) FROM favorite_folders WHERE owner_id = NEW.owner_id) >= 5
        BEGIN
            SELECT RAISE(ABORT, 'FAVORITE_FOLDER_LIMIT_REACHED');
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_favorite_folder_sprites_limit
        BEFORE INSERT ON favorite_folder_sprites
        WHEN (
            SELECT COUNT(*)
            FROM favorite_folder_sprites
            WHERE folder_id = NEW.folder_id
        ) >= 100
        BEGIN
            SELECT RAISE(ABORT, 'FAVORITE_FOLDER_FULL');
        END
        """
    )


def downgrade() -> None:
    """Remove the complete platform schema."""
    op.execute("DROP TRIGGER IF EXISTS trg_favorite_folder_sprites_limit")
    op.execute("DROP TRIGGER IF EXISTS trg_favorite_folders_limit")
    op.drop_index(
        "idx_favorite_folder_sprites_created_at",
        table_name="favorite_folder_sprites",
    )
    op.drop_index(
        "idx_favorite_folder_sprites_sprite_id",
        table_name="favorite_folder_sprites",
    )
    op.drop_table("favorite_folder_sprites")
    op.drop_index("idx_favorite_folders_created_at", table_name="favorite_folders")
    op.drop_index("idx_favorite_folders_owner_id", table_name="favorite_folders")
    op.drop_table("favorite_folders")
    op.drop_index("idx_pack_sprites_sprite_id", table_name="pack_sprites")
    op.drop_table("pack_sprites")
    op.drop_index("idx_packs_owner_id", table_name="packs")
    op.drop_table("packs")
    op.drop_index("idx_sprites_owner_id", table_name="sprites")
    op.drop_index("idx_sprites_created_at", table_name="sprites")
    op.drop_table("sprites")
    op.drop_table("users")
