"""mea culpa on posts

Revision ID: 238faf5c9b8d
Revises: 5fb8f21295da
Create Date: 2023-12-14 20:50:05.043660

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '238faf5c9b8d'
down_revision = '5fb8f21295da'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('post', schema=None) as batch_op:
        batch_op.add_column(sa.Column('mea_culpa', sa.Boolean(), nullable=True))

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('post', schema=None) as batch_op:
        batch_op.drop_column('mea_culpa')

    # ### end Alembic commands ###
