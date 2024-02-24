"""community outbox url

Revision ID: a937c8721612
Revises: 8ca0f0789040
Create Date: 2024-02-21 08:14:23.088264

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a937c8721612'
down_revision = '8ca0f0789040'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('community', schema=None) as batch_op:
        batch_op.add_column(sa.Column('ap_outbox_url', sa.String(length=255), nullable=True))

    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.add_column(sa.Column('email_unread', sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column('email_unread_sent', sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column('email_messages', sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column('email_messages_sent', sa.Boolean(), nullable=True))

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.drop_column('email_messages_sent')
        batch_op.drop_column('email_messages')
        batch_op.drop_column('email_unread_sent')
        batch_op.drop_column('email_unread')

    with op.batch_alter_table('community', schema=None) as batch_op:
        batch_op.drop_column('ap_outbox_url')

    # ### end Alembic commands ###