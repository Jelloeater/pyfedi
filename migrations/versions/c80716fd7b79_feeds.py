"""feeds

Revision ID: c80716fd7b79
Revises: 3f17b9ab55e4
Create Date: 2023-12-31 12:05:39.109343

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c80716fd7b79'
down_revision = '3f17b9ab55e4'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('community', schema=None) as batch_op:
        batch_op.add_column(sa.Column('content_retention', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('show_home', sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column('show_popular', sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column('show_all', sa.Boolean(), nullable=True))

    with op.batch_alter_table('instance', schema=None) as batch_op:
        batch_op.add_column(sa.Column('ip_address', sa.String(length=50), nullable=True))

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('instance', schema=None) as batch_op:
        batch_op.drop_column('ip_address')

    with op.batch_alter_table('community', schema=None) as batch_op:
        batch_op.drop_column('show_all')
        batch_op.drop_column('show_popular')
        batch_op.drop_column('show_home')
        batch_op.drop_column('content_retention')

    # ### end Alembic commands ###
