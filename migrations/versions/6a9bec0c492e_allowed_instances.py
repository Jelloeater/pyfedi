"""allowed instances

Revision ID: 6a9bec0c492e
Revises: c88bbba381b5
Create Date: 2023-11-03 20:23:43.536572

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '6a9bec0c492e'
down_revision = 'c88bbba381b5'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('allowed_instances',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('domain', sa.String(length=256), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('allowed_instances', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_allowed_instances_domain'), ['domain'], unique=False)

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('allowed_instances', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_allowed_instances_domain'))

    op.drop_table('allowed_instances')
    # ### end Alembic commands ###