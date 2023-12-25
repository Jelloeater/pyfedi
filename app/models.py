from datetime import datetime, timedelta, date, timezone
from time import time
from typing import List

from flask import current_app, escape, url_for
from flask_login import UserMixin, current_user
from sqlalchemy import or_, text
from werkzeug.security import generate_password_hash, check_password_hash
from flask_babel import _, lazy_gettext as _l
from sqlalchemy.orm import backref
from sqlalchemy_utils.types import TSVectorType # https://sqlalchemy-searchable.readthedocs.io/en/latest/installation.html
from flask_sqlalchemy import BaseQuery
from sqlalchemy_searchable import SearchQueryMixin
from app import db, login, cache
import jwt
import os

from app.constants import SUBSCRIPTION_NONMEMBER, SUBSCRIPTION_MEMBER, SUBSCRIPTION_MODERATOR, SUBSCRIPTION_OWNER, \
    SUBSCRIPTION_BANNED, SUBSCRIPTION_PENDING


# datetime.utcnow() is depreciated in Python 3.12 so it will need to be swapped out eventually
def utcnow():
    return datetime.utcnow()


class FullTextSearchQuery(BaseQuery, SearchQueryMixin):
    pass


class File(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    file_path = db.Column(db.String(255))
    file_name = db.Column(db.String(255))
    width = db.Column(db.Integer)
    height = db.Column(db.Integer)
    alt_text = db.Column(db.String(256))
    source_url = db.Column(db.String(256))
    thumbnail_path = db.Column(db.String(255))
    thumbnail_width = db.Column(db.Integer)
    thumbnail_height = db.Column(db.Integer)

    def view_url(self):
        if self.source_url:
            return self.source_url
        elif self.file_path:
            file_path = self.file_path[4:] if self.file_path.startswith('app/') else self.file_path
            return f"https://{current_app.config['SERVER_NAME']}/{file_path}"
        else:
            return ''

    def thumbnail_url(self):
        if self.thumbnail_path is None:
            if self.source_url:
                return self.source_url
            else:
                return ''
        thumbnail_path = self.thumbnail_path[4:] if self.thumbnail_path.startswith('app/') else self.thumbnail_path
        return f"https://{current_app.config['SERVER_NAME']}/{thumbnail_path}"

    def delete_from_disk(self):
        if self.file_path and os.path.isfile(self.file_path):
            os.unlink(self.file_path)
        if self.thumbnail_path and os.path.isfile(self.thumbnail_path):
            os.unlink(self.thumbnail_path)


class Community(db.Model):
    query_class = FullTextSearchQuery
    id = db.Column(db.Integer, primary_key=True)
    icon_id = db.Column(db.Integer, db.ForeignKey('file.id'))
    image_id = db.Column(db.Integer, db.ForeignKey('file.id'))
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    name = db.Column(db.String(256), index=True)
    title = db.Column(db.String(256))
    description = db.Column(db.Text)        # markdown
    description_html = db.Column(db.Text)   # html equivalent of above markdown
    rules = db.Column(db.Text)
    rules_html = db.Column(db.Text)
    content_warning = db.Column(db.Text)        # "Are you sure you want to view this community?"
    subscriptions_count = db.Column(db.Integer, default=0)
    post_count = db.Column(db.Integer, default=0)
    post_reply_count = db.Column(db.Integer, default=0)
    nsfw = db.Column(db.Boolean, default=False)
    nsfl = db.Column(db.Boolean, default=False)
    instance_id = db.Column(db.Integer, db.ForeignKey('instance.id'), index=True)
    low_quality = db.Column(db.Boolean, default=False)      # upvotes earned in low quality communities don't improve reputation
    created_at = db.Column(db.DateTime, default=utcnow)
    last_active = db.Column(db.DateTime, default=utcnow)
    public_key = db.Column(db.Text)
    private_key = db.Column(db.Text)

    ap_id = db.Column(db.String(255), index=True)
    ap_profile_id = db.Column(db.String(255), index=True)
    ap_followers_url = db.Column(db.String(255))
    ap_preferred_username = db.Column(db.String(255))
    ap_discoverable = db.Column(db.Boolean, default=False)
    ap_public_url = db.Column(db.String(255))
    ap_fetched_at = db.Column(db.DateTime)
    ap_deleted_at = db.Column(db.DateTime)
    ap_inbox_url = db.Column(db.String(255))
    ap_moderators_url = db.Column(db.String(255))
    ap_domain = db.Column(db.String(255))

    banned = db.Column(db.Boolean, default=False)
    restricted_to_mods = db.Column(db.Boolean, default=False)
    new_mods_wanted = db.Column(db.Boolean, default=False)
    searchable = db.Column(db.Boolean, default=True)
    private_mods = db.Column(db.Boolean, default=False)

    search_vector = db.Column(TSVectorType('name', 'title', 'description', 'rules'))

    posts = db.relationship('Post', backref='community', lazy='dynamic', cascade="all, delete-orphan")
    replies = db.relationship('PostReply', backref='community', lazy='dynamic', cascade="all, delete-orphan")
    icon = db.relationship('File', foreign_keys=[icon_id], single_parent=True, backref='community', cascade="all, delete-orphan")
    image = db.relationship('File', foreign_keys=[image_id], single_parent=True, cascade="all, delete-orphan")

    @cache.memoize(timeout=500)
    def icon_image(self, size='default') -> str:
        if self.icon_id is not None:
            if size == 'default':
                if self.icon.file_path is not None:
                    if self.icon.file_path.startswith('app/'):
                        return self.icon.file_path.replace('app/', '/')
                    else:
                        return self.icon.file_path
                if self.icon.source_url is not None:
                    if self.icon.source_url.startswith('app/'):
                        return self.icon.source_url.replace('app/', '/')
                    else:
                        return self.icon.source_url
            elif size == 'tiny':
                if self.icon.thumbnail_path is not None:
                    if self.icon.thumbnail_path.startswith('app/'):
                        return self.icon.thumbnail_path.replace('app/', '/')
                    else:
                        return self.icon.thumbnail_path
                if self.icon.source_url is not None:
                    if self.icon.source_url.startswith('app/'):
                        return self.icon.source_url.replace('app/', '/')
                    else:
                        return self.icon.source_url
        return ''

    @cache.memoize(timeout=500)
    def header_image(self) -> str:
        if self.image_id is not None:
            if self.image.file_path is not None:
                if self.image.file_path.startswith('app/'):
                    return self.image.file_path.replace('app/', '/')
                else:
                    return self.image.file_path
            if self.image.source_url is not None:
                if self.image.source_url.startswith('app/'):
                    return self.image.source_url.replace('app/', '/')
                else:
                    return self.image.source_url
        return ''

    def display_name(self) -> str:
        if self.ap_id is None:
            return self.title
        else:
            return f"{self.title}@{self.ap_domain}"

    def link(self) -> str:
        if self.ap_id is None:
            return self.name
        else:
            return self.ap_id

    def moderators(self):
        return CommunityMember.query.filter((CommunityMember.community_id == self.id) &
                                     (or_(
                                         CommunityMember.is_owner,
                                         CommunityMember.is_moderator
                                     ))
                                     ).all()

    def is_moderator(self, user=None):
        if user is None:
            return any(moderator.user_id == current_user.id for moderator in self.moderators())
        else:
            return any(moderator.user_id == user.id for moderator in self.moderators())

    def is_owner(self, user=None):
        if user is None:
            return any(moderator.user_id == current_user.id and moderator.is_owner for moderator in self.moderators())
        else:
            return any(moderator.user_id == user.id and moderator.is_owner for moderator in self.moderators())

    def profile_id(self):
        return self.ap_profile_id if self.ap_profile_id else f"https://{current_app.config['SERVER_NAME']}/c/{self.name}"

    def is_local(self):
        return self.ap_id is None or self.profile_id().startswith('https://' + current_app.config['SERVER_NAME'])

    def local_url(self):
        if self.is_local():
            return self.ap_profile_id
        else:
            return f"https://{current_app.config['SERVER_NAME']}/c/{self.ap_id}"

    def delete_dependencies(self):
        # this will be fine for remote communities but for local ones it is necessary to federate every deletion out to subscribers
        for post in self.posts:
            post.delete_dependencies()
            db.session.delete(post)
        db.session.query(CommunityBan).filter(CommunityBan.community_id == self.id).delete()
        db.session.query(CommunityBlock).filter(CommunityBlock.community_id == self.id).delete()
        db.session.query(CommunityJoinRequest).filter(CommunityJoinRequest.community_id == self.id).delete()
        db.session.query(CommunityMember).filter(CommunityMember.community_id == self.id).delete()
        db.session.query(Report).filter(Report.suspect_community_id == self.id).delete()


user_role = db.Table('user_role',
    db.Column('user_id', db.Integer, db.ForeignKey('user.id')),
    db.Column('role_id', db.Integer, db.ForeignKey('role.id')),
    db.PrimaryKeyConstraint('user_id', 'role_id')
)


class User(UserMixin, db.Model):
    query_class = FullTextSearchQuery
    id = db.Column(db.Integer, primary_key=True)
    user_name = db.Column(db.String(255), index=True)
    email = db.Column(db.String(255), index=True)
    password_hash = db.Column(db.String(128))
    verified = db.Column(db.Boolean, default=False)
    verification_token = db.Column(db.String(16), index=True)
    banned = db.Column(db.Boolean, default=False)
    deleted = db.Column(db.Boolean, default=False)
    about = db.Column(db.Text)      # markdown
    about_html = db.Column(db.Text) # html
    keywords = db.Column(db.String(256))
    show_nsfw = db.Column(db.Boolean, default=False)
    show_nsfl = db.Column(db.Boolean, default=False)
    created = db.Column(db.DateTime, default=utcnow)
    last_seen = db.Column(db.DateTime, default=utcnow, index=True)
    avatar_id = db.Column(db.Integer, db.ForeignKey('file.id'))
    cover_id = db.Column(db.Integer, db.ForeignKey('file.id'))
    public_key = db.Column(db.Text)
    private_key = db.Column(db.Text)
    newsletter = db.Column(db.Boolean, default=True)
    bounces = db.Column(db.SmallInteger, default=0)
    timezone = db.Column(db.String(20))
    reputation = db.Column(db.Float, default=0.0)
    attitude = db.Column(db.Float, default=1.0)  # (upvotes cast - downvotes cast) / (upvotes + downvotes). A number between 1 and -1 is the ratio between up and down votes they cast
    stripe_customer_id = db.Column(db.String(50))
    stripe_subscription_id = db.Column(db.String(50))
    searchable = db.Column(db.Boolean, default=True)
    indexable = db.Column(db.Boolean, default=False)
    bot = db.Column(db.Boolean, default=False)
    ignore_bots = db.Column(db.Boolean, default=False)
    unread_notifications = db.Column(db.Integer, default=0)
    instance_id = db.Column(db.Integer, db.ForeignKey('instance.id'), index=True)

    avatar = db.relationship('File', lazy='joined', foreign_keys=[avatar_id], single_parent=True, cascade="all, delete-orphan")
    cover = db.relationship('File', lazy='joined', foreign_keys=[cover_id], single_parent=True, cascade="all, delete-orphan")

    ap_id = db.Column(db.String(255), index=True)           # e.g. username@server
    ap_profile_id = db.Column(db.String(255), index=True)   # e.g. https://server/u/username
    ap_public_url = db.Column(db.String(255))               # e.g. https://server/u/username
    ap_fetched_at = db.Column(db.DateTime)
    ap_followers_url = db.Column(db.String(255))
    ap_preferred_username = db.Column(db.String(255))
    ap_manually_approves_followers = db.Column(db.Boolean)
    ap_deleted_at = db.Column(db.DateTime)
    ap_inbox_url = db.Column(db.String(255))
    ap_domain = db.Column(db.String(255))

    search_vector = db.Column(TSVectorType('user_name', 'bio', 'keywords'))
    activity = db.relationship('ActivityLog', backref='account', lazy='dynamic', cascade="all, delete-orphan")
    posts = db.relationship('Post', lazy='dynamic', cascade="all, delete-orphan")
    post_replies = db.relationship('PostReply', backref='author', lazy='dynamic', cascade="all, delete-orphan")

    roles = db.relationship('Role', secondary=user_role, lazy='dynamic', cascade="all, delete")

    def __repr__(self):
        return '<User {}>'.format(self.user_name)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        try:
            result = check_password_hash(self.password_hash, password)
            return result
        except Exception:
            return False

    def display_name(self):
        if self.deleted is False:
            return self.user_name
        else:
            return '[deleted]'

    def avatar_thumbnail(self) -> str:
        if self.avatar_id is not None:
            if self.avatar.thumbnail_path is not None:
                if self.avatar.thumbnail_path.startswith('app/'):
                    return self.avatar.thumbnail_path.replace('app/', '/')
                else:
                    return self.avatar.thumbnail_path
            else:
                return self.avatar_image()
        return ''

    def avatar_image(self) -> str:
        if self.avatar_id is not None:
            if self.avatar.file_path is not None:
                if self.avatar.file_path.startswith('app/'):
                    return self.avatar.file_path.replace('app/', '/')
                else:
                    return self.avatar.file_path
            if self.avatar.source_url is not None:
                if self.avatar.source_url.startswith('app/'):
                    return self.avatar.source_url.replace('app/', '/')
                else:
                    return self.avatar.source_url
        return ''

    def cover_image(self) -> str:
        if self.cover_id is not None:
            if self.cover.file_path is not None:
                if self.cover.file_path.startswith('app/'):
                    return self.cover.file_path.replace('app/', '/')
                else:
                    return self.cover.file_path
            if self.cover.source_url is not None:
                if self.cover.source_url.startswith('app/'):
                    return self.cover.source_url.replace('app/', '/')
                else:
                    return self.cover.source_url
        return ''

    def is_local(self):
        return self.ap_id is None or self.ap_profile_id.startswith('https://' + current_app.config['SERVER_NAME'])

    def is_admin(self):
        for role in self.roles:
            if role.name == 'Admin':
                return True
        return False

    def link(self) -> str:
        if self.is_local():
            return self.user_name
        else:
            return self.ap_id

    def followers_url(self):
        if self.ap_followers_url:
            return self.ap_followers_url
        else:
            return self.profile_id() + '/followers'

    def get_reset_password_token(self, expires_in=600):
        return jwt.encode(
            {'reset_password': self.id, 'exp': time() + expires_in},
            current_app.config['SECRET_KEY'],
            algorithm='HS256')

    def another_account_using_email(self, email):
        another_account = User.query.filter(User.email == email, User.id != self.id).first()
        return another_account is not None

    def expires_soon(self):
        if self.expires is None:
            return False
        return self.expires < utcnow() + timedelta(weeks=1)

    def is_expired(self):
        if self.expires is None:
            return True
        return self.expires < utcnow()

    def expired_ages_ago(self):
        if self.expires is None:
            return True
        return self.expires < datetime(2019, 9, 1)

    def subscribed(self, community_id: int) -> int:
        if community_id is None:
            return False
        subscription:CommunityMember = CommunityMember.query.filter_by(user_id=self.id, community_id=community_id).first()
        if subscription:
            if subscription.is_banned:
                return SUBSCRIPTION_BANNED
            elif subscription.is_owner:
                return SUBSCRIPTION_OWNER
            elif subscription.is_moderator:
                return SUBSCRIPTION_MODERATOR
            else:
                return SUBSCRIPTION_MEMBER
        else:
            join_request = CommunityJoinRequest.query.filter_by(user_id=self.id, community_id=community_id).first()
            if join_request:
                return SUBSCRIPTION_PENDING
            else:
                return SUBSCRIPTION_NONMEMBER

    def communities(self) -> List[Community]:
        return Community.query.filter(Community.banned == False).\
            join(CommunityMember).filter(CommunityMember.is_banned == False).all()

    def profile_id(self):
        return self.ap_profile_id if self.ap_profile_id else f"https://{current_app.config['SERVER_NAME']}/u/{self.user_name}"

    def created_recently(self):
        return self.created and self.created > utcnow() - timedelta(days=7)

    @staticmethod
    def verify_reset_password_token(token):
        try:
            id = jwt.decode(token, current_app.config['SECRET_KEY'],
                            algorithms=['HS256'])['reset_password']
        except:
            return
        return User.query.get(id)

    def flush_cache(self):
        cache.delete('/u/' + self.user_name + '_False')
        cache.delete('/u/' + self.user_name + '_True')

    def purge_content(self):
        files = File.query.join(Post).filter(Post.user_id == self.id).all()
        for file in files:
            file.delete_from_disk()
        db.session.query(Report).filter(Report.reporter_id == self.id).delete()
        db.session.query(Report).filter(Report.suspect_user_id == self.id).delete()
        db.session.query(ActivityLog).filter(ActivityLog.user_id == self.id).delete()
        db.session.query(PostVote).filter(PostVote.user_id == self.id).delete()
        db.session.query(PostReplyVote).filter(PostReplyVote.user_id == self.id).delete()
        db.session.query(PostReply).filter(PostReply.user_id == self.id).delete()
        db.session.query(FilterKeyword).filter(FilterKeyword.user_id == self.id).delete()
        db.session.query(Filter).filter(Filter.user_id == self.id).delete()
        db.session.query(DomainBlock).filter(DomainBlock.user_id == self.id).delete()
        db.session.query(CommunityJoinRequest).filter(CommunityJoinRequest.user_id == self.id).delete()
        db.session.query(CommunityMember).filter(CommunityMember.user_id == self.id).delete()
        db.session.query(CommunityBlock).filter(CommunityBlock.user_id == self.id).delete()
        db.session.query(CommunityBan).filter(CommunityBan.user_id == self.id).delete()
        db.session.query(Community).filter(Community.user_id == self.id).delete()
        db.session.query(Post).filter(Post.user_id == self.id).delete()
        db.session.query(UserNote).filter(UserNote.user_id == self.id).delete()
        db.session.query(UserNote).filter(UserNote.target_id == self.id).delete()
        db.session.query(UserFollowRequest).filter(UserFollowRequest.follow_id == self.id).delete()
        db.session.query(UserFollowRequest).filter(UserFollowRequest.user_id == self.id).delete()
        db.session.query(UserBlock).filter(UserBlock.blocked_id == self.id).delete()
        db.session.query(UserBlock).filter(UserBlock.blocker_id == self.id).delete()
        db.session.execute(text('DELETE FROM user_role WHERE user_id = :user_id'),
                           {'user_id': self.id})


class ActivityLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), index=True)
    activity_type = db.Column(db.String(64))
    activity = db.Column(db.String(255))
    timestamp = db.Column(db.DateTime, index=True, default=utcnow)


class Post(db.Model):
    query_class = FullTextSearchQuery
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), index=True)
    community_id = db.Column(db.Integer, db.ForeignKey('community.id'), index=True)
    image_id = db.Column(db.Integer, db.ForeignKey('file.id'), index=True)
    domain_id = db.Column(db.Integer, db.ForeignKey('domain.id'), index=True)
    instance_id = db.Column(db.Integer, db.ForeignKey('instance.id'), index=True)
    slug = db.Column(db.String(255))
    title = db.Column(db.String(255))
    url = db.Column(db.String(2048))
    body = db.Column(db.Text)
    body_html = db.Column(db.Text)
    type = db.Column(db.Integer)
    comments_enabled = db.Column(db.Boolean, default=True)
    mea_culpa = db.Column(db.Boolean, default=False)
    has_embed = db.Column(db.Boolean, default=False)
    reply_count = db.Column(db.Integer, default=0)
    score = db.Column(db.Integer, default=0, index=True)                # used for 'top' ranking
    nsfw = db.Column(db.Boolean, default=False)
    nsfl = db.Column(db.Boolean, default=False)
    sticky = db.Column(db.Boolean, default=False)
    notify_author = db.Column(db.Boolean, default=True)
    indexable = db.Column(db.Boolean, default=False)
    from_bot = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, index=True, default=utcnow)    # this is when the content arrived here
    posted_at = db.Column(db.DateTime, index=True, default=utcnow)     # this is when the original server created it
    last_active = db.Column(db.DateTime, index=True, default=utcnow)
    ip = db.Column(db.String(50))
    up_votes = db.Column(db.Integer, default=0)
    down_votes = db.Column(db.Integer, default=0)
    ranking = db.Column(db.Integer, default=0)                          # used for 'hot' ranking
    language = db.Column(db.String(10))
    edited_at = db.Column(db.DateTime)
    reports = db.Column(db.Integer, default=0)                          # how many times this post has been reported. Set to -1 to ignore reports

    ap_id = db.Column(db.String(255), index=True)
    ap_create_id = db.Column(db.String(100))
    ap_announce_id = db.Column(db.String(100))

    search_vector = db.Column(TSVectorType('title', 'body'))

    image = db.relationship(File, lazy='joined', foreign_keys=[image_id], cascade="all, delete")
    domain = db.relationship('Domain', lazy='joined', foreign_keys=[domain_id])
    author = db.relationship('User', lazy='joined', overlaps='posts', foreign_keys=[user_id])
    replies = db.relationship('PostReply', lazy='dynamic', backref='post')

    def is_local(self):
        return self.ap_id is None or self.ap_id.startswith('https://' + current_app.config['SERVER_NAME'])

    @classmethod
    def get_by_ap_id(cls, ap_id):
        return cls.query.filter_by(ap_id=ap_id).first()

    def delete_dependencies(self):
        db.session.query(Report).filter(Report.suspect_post_id == self.id).delete()
        db.session.execute(text('DELETE FROM post_reply_vote WHERE post_reply_id IN (SELECT id FROM post_reply WHERE post_id = :post_id)'),
                           {'post_id': self.id})
        db.session.execute(text('DELETE FROM post_reply WHERE post_id = :post_id'), {'post_id': self.id})
        db.session.execute(text('DELETE FROM post_vote WHERE post_id = :post_id'), {'post_id': self.id})
        if self.image_id:
            file = File.query.get(self.image_id)
            file.delete_from_disk()

    def youtube_embed(self):
        if self.url:
            vpos = self.url.find('v=')
            if vpos != -1:
                return self.url[vpos + 2:vpos + 13]

    def profile_id(self):
        if self.ap_id:
            return self.ap_id
        else:
            return f"https://{current_app.config['SERVER_NAME']}/post/{self.id}"

    def flush_cache(self):
        cache.delete(f'/post/{self.id}_False')
        cache.delete(f'/post/{self.id}_True')


class PostReply(db.Model):
    query_class = FullTextSearchQuery
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), index=True)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), index=True)
    community_id = db.Column(db.Integer, db.ForeignKey('community.id'), index=True)
    domain_id = db.Column(db.Integer, db.ForeignKey('domain.id'), index=True)
    image_id = db.Column(db.Integer, db.ForeignKey('file.id'), index=True)
    parent_id = db.Column(db.Integer)
    root_id = db.Column(db.Integer)
    depth = db.Column(db.Integer, default=0)
    body = db.Column(db.Text)
    body_html = db.Column(db.Text)
    body_html_safe = db.Column(db.Boolean, default=False)
    score = db.Column(db.Integer, default=0, index=True)    # used for 'top' sorting
    nsfw = db.Column(db.Boolean, default=False)
    nsfl = db.Column(db.Boolean, default=False)
    notify_author = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, index=True, default=utcnow)
    posted_at = db.Column(db.DateTime, index=True, default=utcnow)
    ip = db.Column(db.String(50))
    from_bot = db.Column(db.Boolean, default=False)
    up_votes = db.Column(db.Integer, default=0)
    down_votes = db.Column(db.Integer, default=0)
    ranking = db.Column(db.Integer, default=0, index=True)  # used for 'hot' sorting
    language = db.Column(db.String(10))
    edited_at = db.Column(db.DateTime)
    reports = db.Column(db.Integer, default=0)  # how many times this post has been reported. Set to -1 to ignore reports

    ap_id = db.Column(db.String(255), index=True)
    ap_create_id = db.Column(db.String(100))
    ap_announce_id = db.Column(db.String(100))

    search_vector = db.Column(TSVectorType('body'))

    def is_local(self):
        return self.ap_id is None or self.ap_id.startswith('https://' + current_app.config['SERVER_NAME'])

    @classmethod
    def get_by_ap_id(cls, ap_id):
        return cls.query.filter_by(ap_id=ap_id).first()

    def profile_id(self):
        if self.ap_id:
            return self.ap_id
        else:
            return f"https://{current_app.config['SERVER_NAME']}/comment/{self.id}"

    # the ap_id of the parent object, whether it's another PostReply or a Post
    def in_reply_to(self):
        if self.parent_id is None:
            return self.post.ap_id
        else:
            parent = PostReply.query.get(self.parent_id)
            return parent.ap_id

    # the AP profile of the person who wrote the parent object, which could be another PostReply or a Post
    def to(self):
        if self.parent_id is None:
            return self.post.author.profile_id()
        else:
            parent = PostReply.query.get(self.parent_id)
            return parent.author.profile_id()

    def delete_dependencies(self):
        db.session.query(Report).filter(Report.suspect_post_reply_id == self.id).delete()
        db.session.execute(text('DELETE FROM post_reply_vote WHERE post_reply_id = :post_reply_id'),
                           {'post_reply_id': self.id})
        if self.image_id:
            file = File.query.get(self.image_id)
            file.delete_from_disk()

    def has_replies(self):
        reply = PostReply.query.filter_by(parent_id=self.id).first()
        return reply is not None


class Domain(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), index=True)
    post_count = db.Column(db.Integer, default=0)
    banned = db.Column(db.Boolean, default=False, index=True) # Domains can be banned site-wide (by admin) or DomainBlock'ed by users


class DomainBlock(db.Model):
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), primary_key=True)
    domain_id = db.Column(db.Integer, db.ForeignKey('domain.id'), primary_key=True)
    created_at = db.Column(db.DateTime, default=utcnow)


class CommunityBlock(db.Model):
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), primary_key=True)
    community_id = db.Column(db.Integer, db.ForeignKey('community.id'), primary_key=True)
    created_at = db.Column(db.DateTime, default=utcnow)


class CommunityMember(db.Model):
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), primary_key=True)
    community_id = db.Column(db.Integer, db.ForeignKey('community.id'), primary_key=True)
    is_moderator = db.Column(db.Boolean, default=False)
    is_owner = db.Column(db.Boolean, default=False)
    is_banned = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=utcnow)


# people banned from communities
class CommunityBan(db.Model):
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), primary_key=True)
    community_id = db.Column(db.Integer, db.ForeignKey('community.id'), primary_key=True)
    banned_by = db.Column(db.Integer, db.ForeignKey('user.id'))
    reason = db.Column(db.String(50))
    created_at = db.Column(db.DateTime, default=utcnow)
    ban_until = db.Column(db.DateTime)


class UserNote(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    target_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    body = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=utcnow)


class UserBlock(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    blocker_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    blocked_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    created_at = db.Column(db.DateTime, default=utcnow)


class BannedInstances(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    domain = db.Column(db.String(256), index=True)
    reason = db.Column(db.String(256))
    initiator = db.Column(db.String(256))
    created_at = db.Column(db.DateTime, default=utcnow)


class AllowedInstances(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    domain = db.Column(db.String(256), index=True)
    created_at = db.Column(db.DateTime, default=utcnow)


class Instance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    domain = db.Column(db.String(256), index=True)
    inbox = db.Column(db.String(256))
    shared_inbox = db.Column(db.String(256))
    outbox = db.Column(db.String(256))
    vote_weight = db.Column(db.Float, default=1.0)
    software = db.Column(db.String(50))
    version = db.Column(db.String(50))
    created_at = db.Column(db.DateTime, default=utcnow)
    updated_at = db.Column(db.DateTime, default=utcnow)

    posts = db.relationship('Post', backref='instance', lazy='dynamic')
    communities = db.relationship('Community', backref='instance', lazy='dynamic')


class InstanceBlock(db.Model):
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), primary_key=True)
    instance_id = db.Column(db.Integer, db.ForeignKey('instance.id'), primary_key=True)
    created_at = db.Column(db.DateTime, default=utcnow)


class Settings(db.Model):
    name = db.Column(db.String(50), primary_key=True)
    value = db.Column(db.String(1024))


class Interest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50))
    communities = db.Column(db.Text)


class CommunityJoinRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    community_id = db.Column(db.Integer, db.ForeignKey('community.id'))


class UserFollowRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    follow_id = db.Column(db.Integer, db.ForeignKey('user.id'))


class PostVote(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    author_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'))
    effect = db.Column(db.Float)
    created_at = db.Column(db.DateTime, default=utcnow)
    post = db.relationship('Post', foreign_keys=[post_id])


class PostReplyVote(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))   # who voted
    author_id = db.Column(db.Integer, db.ForeignKey('user.id')) # the author of the reply voted on - who's reputation is affected
    post_reply_id = db.Column(db.Integer, db.ForeignKey('post_reply.id'))
    effect = db.Column(db.Float)
    created_at = db.Column(db.DateTime, default=utcnow)


# save every activity to a log, to aid debugging
class ActivityPubLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    direction = db.Column(db.String(3))         # 'in' or 'out'
    activity_id = db.Column(db.String(100), index=True)
    activity_type = db.Column(db.String(50))    # e.g. 'Follow', 'Accept', 'Like', etc
    activity_json = db.Column(db.Text)          # the full json of the activity
    result = db.Column(db.String(10))           # 'success' or 'failure'
    exception_message = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=utcnow)


class Filter(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(50))
    filter_posts = db.Column(db.Boolean, default=True)
    filter_replies = db.Column(db.Boolean, default=False)
    hide_type = db.Column(db.Integer, default=0)    # 0 = hide with warning, 1 = hide completely
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))


class FilterKeyword(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    keyword = db.Column(db.String(100))
    filter_id = db.Column(db.Integer, db.ForeignKey('filter.id'))
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))


class Role(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50))
    weight = db.Column(db.Integer, default=0)
    permissions = db.relationship('RolePermission')


class RolePermission(db.Model):
    role_id = db.Column(db.Integer, db.ForeignKey('role.id'), primary_key=True)
    permission = db.Column(db.String, primary_key=True, index=True)


class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(50))
    url = db.Column(db.String(512))
    read = db.Column(db.Boolean, default=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    author_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    created_at = db.Column(db.DateTime, default=utcnow)


class Report(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    reasons = db.Column(db.String(256))
    description = db.Column(db.String(256))
    status = db.Column(db.Integer, default=0)
    type = db.Column(db.Integer, default=0)     # 0 = user, 1 = post, 2 = reply, 3 = community
    reporter_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    suspect_community_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    suspect_user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    suspect_post_id = db.Column(db.Integer, db.ForeignKey('post.id'))
    suspect_post_reply_id = db.Column(db.Integer, db.ForeignKey('post_reply.id'))
    suspect_reply_id = db.Column(db.Integer, db.ForeignKey('post_reply.id'))
    created_at = db.Column(db.DateTime, default=utcnow)
    updated = db.Column(db.DateTime, default=utcnow)


class Site(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(256))
    description = db.Column(db.String(256))
    icon_id = db.Column(db.Integer, db.ForeignKey('file.id'))
    sidebar = db.Column(db.Text, default='')
    legal_information = db.Column(db.Text, default='')
    public_key = db.Column(db.Text)
    private_key = db.Column(db.Text)
    enable_downvotes = db.Column(db.Boolean, default=True)
    allow_local_image_posts = db.Column(db.Boolean, default=True)
    remote_image_cache_days = db.Column(db.Integer, default=30)
    enable_nsfw = db.Column(db.Boolean, default=False)
    enable_nsfl = db.Column(db.Boolean, default=False)
    community_creation_admin_only = db.Column(db.Boolean, default=False)
    reports_email_admins = db.Column(db.Boolean, default=True)
    registration_mode = db.Column(db.String(20), default='Closed')
    application_question = db.Column(db.Text, default='')
    allow_or_block_list = db.Column(db.Integer, default=2)  # 1 = allow list, 2 = block list
    allowlist = db.Column(db.Text, default='')
    blocklist = db.Column(db.Text, default='')
    created_at = db.Column(db.DateTime, default=utcnow)
    updated = db.Column(db.DateTime, default=utcnow)
    last_active = db.Column(db.DateTime, default=utcnow)


@login.user_loader
def load_user(id):
    return User.query.get(int(id))
