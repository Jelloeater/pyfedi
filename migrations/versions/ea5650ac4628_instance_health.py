"""instance health

Revision ID: ea5650ac4628
Revises: 88d210da7f2b
Create Date: 2023-12-29 20:26:42.527252

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'ea5650ac4628'
down_revision = '88d210da7f2b'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('instance', schema=None) as batch_op:
        batch_op.add_column(sa.Column('last_seen', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('last_successful_send', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('failures', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('most_recent_attempt', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('dormant', sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column('start_trying_again', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('gone_forever', sa.Boolean(), nullable=True))

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('instance', schema=None) as batch_op:
        batch_op.drop_column('gone_forever')
        batch_op.drop_column('start_trying_again')
        batch_op.drop_column('dormant')
        batch_op.drop_column('most_recent_attempt')
        batch_op.drop_column('failures')
        batch_op.drop_column('last_successful_send')
        batch_op.drop_column('last_seen')

    # ### end Alembic commands ###
