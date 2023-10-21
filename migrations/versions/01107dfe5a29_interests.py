"""interests

Revision ID: 01107dfe5a29
Revises: 755fa58fd603
Create Date: 2023-09-05 20:02:29.542729

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '01107dfe5a29'
down_revision = '755fa58fd603'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('interest',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=50), nullable=True),
    sa.Column('communities', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_table('interest')
    # ### end Alembic commands ###