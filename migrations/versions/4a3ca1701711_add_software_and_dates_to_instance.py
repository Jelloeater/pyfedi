"""add software and dates to instance

Revision ID: 4a3ca1701711
Revises: 84a5cb2a5e5b
Create Date: 2023-11-23 14:33:06.928554

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '4a3ca1701711'
down_revision = '84a5cb2a5e5b'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('instance', schema=None) as batch_op:
        batch_op.add_column(sa.Column('software', sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column('version', sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column('created_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('updated_at', sa.DateTime(), nullable=True))

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('instance', schema=None) as batch_op:
        batch_op.drop_column('updated_at')
        batch_op.drop_column('created_at')
        batch_op.drop_column('version')
        batch_op.drop_column('software')

    # ### end Alembic commands ###
