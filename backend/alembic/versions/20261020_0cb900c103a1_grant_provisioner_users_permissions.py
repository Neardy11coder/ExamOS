"""grant_provisioner_users_permissions

Revision ID: 0cb900c103a1
Revises: 2efc4c54e793
Create Date: 2026-10-20 13:45:04.863499

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0cb900c103a1'
down_revision: Union[str, None] = '2efc4c54e793'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Grant least-privilege SELECT, INSERT specifically on public.users to examos_provisioner if role exists
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'examos_provisioner') THEN
                GRANT SELECT, INSERT ON TABLE public.users TO examos_provisioner;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    # Revoke SELECT, INSERT on public.users from examos_provisioner if role exists
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'examos_provisioner') THEN
                REVOKE SELECT, INSERT ON TABLE public.users FROM examos_provisioner;
            END IF;
        END $$;
        """
    )
