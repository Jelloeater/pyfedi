"""report_block

Revision ID: 31dfc1d1d3f6
Revises: b36dac7696d1
Create Date: 2023-12-13 19:11:27.447598

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '31dfc1d1d3f6'
down_revision = 'b36dac7696d1'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('instance_block',
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('instance_id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['instance_id'], ['instance.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['user.id'], ),
    sa.PrimaryKeyConstraint('user_id', 'instance_id')
    )
    op.create_table('report',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('reasons', sa.String(length=256), nullable=True),
    sa.Column('description', sa.String(length=256), nullable=True),
    sa.Column('status', sa.Integer(), nullable=True),
    sa.Column('type', sa.Integer(), nullable=True),
    sa.Column('reporter_id', sa.Integer(), nullable=True),
    sa.Column('suspect_community_id', sa.Integer(), nullable=True),
    sa.Column('suspect_user_id', sa.Integer(), nullable=True),
    sa.Column('suspect_post_id', sa.Integer(), nullable=True),
    sa.Column('suspect_reply_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['reporter_id'], ['user.id'], ),
    sa.ForeignKeyConstraint(['suspect_community_id'], ['user.id'], ),
    sa.ForeignKeyConstraint(['suspect_post_id'], ['post.id'], ),
    sa.ForeignKeyConstraint(['suspect_reply_id'], ['post_reply.id'], ),
    sa.ForeignKeyConstraint(['suspect_user_id'], ['user.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('community', schema=None) as batch_op:
        batch_op.add_column(sa.Column('content_warning', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('low_quality', sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column('new_mods_wanted', sa.Boolean(), nullable=True))

    with op.batch_alter_table('post', schema=None) as batch_op:
        batch_op.add_column(sa.Column('instance_id', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_post_instance_id'), ['instance_id'], unique=False)
        batch_op.create_foreign_key(None, 'instance', ['instance_id'], ['id'])

    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.add_column(sa.Column('attitude', sa.Float(), nullable=True))

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.drop_column('attitude')

    with op.batch_alter_table('post', schema=None) as batch_op:
        batch_op.drop_constraint(None, type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_post_instance_id'))
        batch_op.drop_column('instance_id')

    with op.batch_alter_table('community', schema=None) as batch_op:
        batch_op.drop_column('new_mods_wanted')
        batch_op.drop_column('low_quality')
        batch_op.drop_column('content_warning')

    op.drop_table('report')
    op.drop_table('instance_block')
    # ### end Alembic commands ###
