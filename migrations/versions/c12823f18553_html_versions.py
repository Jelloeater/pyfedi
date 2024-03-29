"""html versions

Revision ID: c12823f18553
Revises: 72f3326bdf54
Create Date: 2023-12-21 20:21:55.039590

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c12823f18553'
down_revision = '72f3326bdf54'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('community', schema=None) as batch_op:
        batch_op.add_column(sa.Column('description_html', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('rules_html', sa.Text(), nullable=True))

    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.add_column(sa.Column('about_html', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('instance_id', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_user_instance_id'), ['instance_id'], unique=False)
        batch_op.create_foreign_key(None, 'instance', ['instance_id'], ['id'])

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.drop_constraint(None, type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_user_instance_id'))
        batch_op.drop_column('instance_id')
        batch_op.drop_column('about_html')

    with op.batch_alter_table('community', schema=None) as batch_op:
        batch_op.drop_column('rules_html')
        batch_op.drop_column('description_html')

    # ### end Alembic commands ###
