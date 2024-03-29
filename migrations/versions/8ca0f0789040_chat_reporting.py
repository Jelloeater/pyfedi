"""chat reporting

Revision ID: 8ca0f0789040
Revises: b4f7322082f4
Create Date: 2024-02-19 14:58:13.481708

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '8ca0f0789040'
down_revision = 'b4f7322082f4'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('report', schema=None) as batch_op:
        batch_op.add_column(sa.Column('suspect_conversation_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key(None, 'conversation', ['suspect_conversation_id'], ['id'])

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('report', schema=None) as batch_op:
        batch_op.drop_constraint(None, type_='foreignkey')
        batch_op.drop_column('suspect_conversation_id')

    # ### end Alembic commands ###
