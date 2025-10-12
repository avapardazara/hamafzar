"""merge heads (mentor finance)

Revision ID: 527c329c0fda
Revises: extend_payments_for_mentor_finance, 730e10ae2b6c
Create Date: 2025-10-12 19:22:28.826551

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '527c329c0fda'
down_revision = ('extend_payments_for_mentor_finance', '730e10ae2b6c')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
