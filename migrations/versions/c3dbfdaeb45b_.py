"""empty message

Revision ID: c3dbfdaeb45b
Revises: 1fe582999fec
Create Date: 2019-12-01 16:12:12.484573

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c3dbfdaeb45b'
down_revision = '1fe582999fec'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('bridgemetadata',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('created', sa.DateTime(), nullable=True),
    sa.Column('last_tweet', sa.DateTime(), nullable=True),
    sa.Column('last_toot', sa.DateTime(), nullable=True),
    sa.Column('is_bot', sa.Boolean(), server_default='0', nullable=True),
    sa.Column('worker_id', sa.Integer(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.add_column('bridge', sa.Column('metadata_id', sa.Integer(), nullable=True))
    op.create_foreign_key(None, 'bridge', 'bridgemetadata', ['metadata_id'], ['id'])
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_constraint(None, 'bridge', type_='foreignkey')
    op.drop_column('bridge', 'metadata_id')
    op.drop_table('bridgemetadata')
    # ### end Alembic commands ###
