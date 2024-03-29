"""user email addr verification

Revision ID: 93e4cef1698c
Revises: f52c490d4e81
Create Date: 2023-08-26 14:11:13.432192

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '93e4cef1698c'
down_revision = 'f52c490d4e81'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.add_column(sa.Column('verification_token', sa.String(length=16), nullable=True))

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.drop_column('verification_token')

    # ### end Alembic commands ###
