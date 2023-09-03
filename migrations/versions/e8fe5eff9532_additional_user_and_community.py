"""additional user and community

Revision ID: e8fe5eff9532
Revises: 1a9507704262
Create Date: 2023-08-10 21:46:25.190829

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e8fe5eff9532'
down_revision = '1a9507704262'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('instance',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('domain', sa.String(length=256), nullable=True),
    sa.Column('inbox', sa.String(length=256), nullable=True),
    sa.Column('shared_inbox', sa.String(length=256), nullable=True),
    sa.Column('outbox', sa.String(length=256), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('banned_instances', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_banned_instances_domain'), ['domain'], unique=False)

    with op.batch_alter_table('community', schema=None) as batch_op:
        batch_op.add_column(sa.Column('restricted_to_mods', sa.Boolean(), nullable=True))

    with op.batch_alter_table('post', schema=None) as batch_op:
        batch_op.add_column(sa.Column('body_html', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('ap_create_id', sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column('ap_announce_id', sa.String(length=100), nullable=True))

    with op.batch_alter_table('post_reply', schema=None) as batch_op:
        batch_op.add_column(sa.Column('body_html', sa.Text(), nullable=True))

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('post_reply', schema=None) as batch_op:
        batch_op.drop_column('body_html')

    with op.batch_alter_table('post', schema=None) as batch_op:
        batch_op.drop_column('ap_announce_id')
        batch_op.drop_column('ap_create_id')
        batch_op.drop_column('body_html')

    with op.batch_alter_table('community', schema=None) as batch_op:
        batch_op.drop_column('restricted_to_mods')

    with op.batch_alter_table('banned_instances', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_banned_instances_domain'))

    op.drop_table('instance')
    # ### end Alembic commands ###