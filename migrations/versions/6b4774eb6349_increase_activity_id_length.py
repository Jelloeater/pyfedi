"""increase activity id length

Revision ID: 6b4774eb6349
Revises: b86c49cbd9a0
Create Date: 2024-01-19 07:45:25.845475

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '6b4774eb6349'
down_revision = 'b86c49cbd9a0'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('activity_pub_log', schema=None) as batch_op:
        batch_op.alter_column('activity_id',
               existing_type=sa.VARCHAR(length=100),
               type_=sa.String(length=256),
               existing_nullable=True)

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('activity_pub_log', schema=None) as batch_op:
        batch_op.alter_column('activity_id',
               existing_type=sa.String(length=256),
               type_=sa.VARCHAR(length=100),
               existing_nullable=True)

    # ### end Alembic commands ###
