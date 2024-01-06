"""community notifications

Revision ID: dc49309fc13e
Revises: fd5d3a9cb584
Create Date: 2024-01-07 10:35:55.484246

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'dc49309fc13e'
down_revision = 'fd5d3a9cb584'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('community_member', schema=None) as batch_op:
        batch_op.add_column(sa.Column('notify_new_posts', sa.Boolean(), nullable=True))

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('community_member', schema=None) as batch_op:
        batch_op.drop_column('notify_new_posts')

    # ### end Alembic commands ###
