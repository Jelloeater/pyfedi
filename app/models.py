from datetime import datetime, timedelta, date
from hashlib import md5
from time import time
from flask import current_app, escape
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from flask_babel import _, lazy_gettext as _l
from sqlalchemy.orm import backref
from sqlalchemy_utils.types import TSVectorType # https://sqlalchemy-searchable.readthedocs.io/en/latest/installation.html
from app import db, login
import jwt

from app.constants import SUBSCRIPTION_NONMEMBER, SUBSCRIPTION_MEMBER, SUBSCRIPTION_MODERATOR, SUBSCRIPTION_OWNER, \
    SUBSCRIPTION_BANNED


class File(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    file_path = db.Column(db.String(255))
    file_name = db.Column(db.String(255))
    width = db.Column(db.Integer)
    height = db.Column(db.Integer)
    alt_text = db.Column(db.String(256))
    source_url = db.Column(db.String(256))


class Community(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    icon_id = db.Column(db.Integer, db.ForeignKey('file.id'))
    image_id = db.Column(db.Integer, db.ForeignKey('file.id'))
    name = db.Column(db.String(256), index=True)
    title = db.Column(db.String(256))
    description = db.Column(db.Text)
    rules = db.Column(db.Text)
    subscriptions_count = db.Column(db.Integer, default=0)
    post_count = db.Column(db.Integer, default=0)
    post_reply_count = db.Column(db.Integer, default=0)
    nsfw = db.Column(db.Boolean, default=False)
    nsfl = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_active = db.Column(db.DateTime, default=datetime.utcnow)
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
    ap_domain = db.Column(db.String(255))

    banned = db.Column(db.Boolean, default=False)
    restricted_to_mods = db.Column(db.Boolean, default=False)
    searchable = db.Column(db.Boolean, default=True)
    private_mods = db.Column(db.Boolean, default=False)

    search_vector = db.Column(TSVectorType('name', 'title', 'description', 'rules'))

    posts = db.relationship('Post', backref='community', lazy='dynamic', cascade="all, delete-orphan")
    replies = db.relationship('PostReply', backref='community', lazy='dynamic', cascade="all, delete-orphan")
    icon = db.relationship('File', foreign_keys=[icon_id], single_parent=True, backref='community', cascade="all, delete-orphan")
    image = db.relationship('File', foreign_keys=[image_id], single_parent=True, cascade="all, delete-orphan")

    def icon_image(self) -> str:
        if self.icon_id is not None:
            if self.icon.file_path is not None:
                return self.icon.file_path
            if self.icon.source_url is not None:
                return self.icon.source_url
        return ''

    def header_image(self) -> str:
        if self.image_id is not None:
            if self.image.file_path is not None:
                return self.image.file_path
            if self.image.source_url is not None:
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


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_name = db.Column(db.String(255), unique=True, index=True)
    email = db.Column(db.String(255), index=True)
    password_hash = db.Column(db.String(128))
    verified = db.Column(db.Boolean, default=False)
    verification_token = db.Column(db.String(16), index=True)
    banned = db.Column(db.Boolean, default=False)
    deleted = db.Column(db.Boolean, default=False)
    about = db.Column(db.Text)
    keywords = db.Column(db.String(256))
    show_nsfw = db.Column(db.Boolean, default=False)
    show_nsfl = db.Column(db.Boolean, default=False)
    created = db.Column(db.DateTime, default=datetime.utcnow)
    last_seen = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    role = db.Column(db.Integer, default=0)
    avatar_id = db.Column(db.Integer, db.ForeignKey('file.id'))
    cover_id = db.Column(db.Integer, db.ForeignKey('file.id'))
    public_key = db.Column(db.Text)
    private_key = db.Column(db.Text)
    newsletter = db.Column(db.Boolean, default=True)
    bounces = db.Column(db.SmallInteger, default=0)
    timezone = db.Column(db.String(20))
    stripe_customer_id = db.Column(db.String(50))
    stripe_subscription_id = db.Column(db.String(50))
    searchable = db.Column(db.Boolean, default=True)
    indexable = db.Column(db.Boolean, default=False)

    avatar = db.relationship('File', foreign_keys=[avatar_id], single_parent=True, cascade="all, delete-orphan")
    cover = db.relationship('File', foreign_keys=[cover_id], single_parent=True, cascade="all, delete-orphan")

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
    posts = db.relationship('Post', backref='author', lazy='dynamic', cascade="all, delete-orphan")
    post_replies = db.relationship('PostReply', backref='author', lazy='dynamic', cascade="all, delete-orphan")

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

    def avatar(self, size):
        digest = md5(self.email.lower().encode('utf-8')).hexdigest()
        return 'https://www.gravatar.com/avatar/{}?d=identicon&s={}'.format(
            digest, size)

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
        return self.expires < datetime.utcnow() + timedelta(weeks=1)

    def is_expired(self):
        if self.expires is None:
            return True
        return self.expires < datetime.utcnow()

    def expired_ages_ago(self):
        if self.expires is None:
            return True
        return self.expires < datetime(2019, 9, 1)

    def subscribed(self, community: Community) -> int:
        if community is None:
            return False
        subscription:CommunityMember = CommunityMember.query.filter_by(user_id=self.id, community_id=community.id).first()
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
            return SUBSCRIPTION_NONMEMBER

    @staticmethod
    def verify_reset_password_token(token):
        try:
            id = jwt.decode(token, current_app.config['SECRET_KEY'],
                            algorithms=['HS256'])['reset_password']
        except:
            return
        return User.query.get(id)


class ActivityLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), index=True)
    activity_type = db.Column(db.String(64))
    activity = db.Column(db.String(255))
    timestamp = db.Column(db.DateTime, index=True, default=datetime.utcnow)


class Post(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), index=True)
    community_id = db.Column(db.Integer, db.ForeignKey('community.id'), index=True)
    image_id = db.Column(db.Integer, db.ForeignKey('file.id'), index=True)
    domain_id = db.Column(db.Integer, db.ForeignKey('domain.id'), index=True)
    slug = db.Column(db.String(255))
    title = db.Column(db.String(255))
    url = db.Column(db.String(2048))
    body = db.Column(db.Text)
    body_html = db.Column(db.Text)
    type = db.Column(db.Integer)
    has_embed = db.Column(db.Boolean, default=False)
    reply_count = db.Column(db.Integer, default=0)
    score = db.Column(db.Integer, default=0, index=True)
    nsfw = db.Column(db.Boolean, default=False)
    nsfl = db.Column(db.Boolean, default=False)
    sticky = db.Column(db.Boolean, default=False)
    indexable = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, index=True, default=datetime.utcnow)
    posted_at = db.Column(db.DateTime, index=True, default=datetime.utcnow)
    last_active = db.Column(db.DateTime, index=True, default=datetime.utcnow)
    ip = db.Column(db.String(50))
    up_votes = db.Column(db.Integer, default=0)
    down_votes = db.Column(db.Integer, default=0)
    ranking = db.Column(db.Integer, default=0)
    language = db.Column(db.String(10))
    edited_at = db.Column(db.DateTime)

    ap_id = db.Column(db.String(255), index=True)
    ap_create_id = db.Column(db.String(100))
    ap_announce_id = db.Column(db.String(100))

    search_vector = db.Column(TSVectorType('title', 'body'))

    image = db.relationship(File, foreign_keys=[image_id], cascade="all, delete")


class PostReply(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), index=True)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), index=True)
    community_id = db.Column(db.Integer, db.ForeignKey('community.id'), index=True)
    image_id = db.Column(db.Integer, db.ForeignKey('file.id'), index=True)
    parent_id = db.Column(db.Integer)
    root_id = db.Column(db.Integer)
    body = db.Column(db.Text)
    body_html = db.Column(db.Text)
    score = db.Column(db.Integer, default=0, index=True)
    nsfw = db.Column(db.Boolean, default=False)
    nsfl = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, index=True, default=datetime.utcnow)
    posted_at = db.Column(db.DateTime, index=True, default=datetime.utcnow)
    ip = db.Column(db.String(50))
    up_votes = db.Column(db.Integer, default=0)
    down_votes = db.Column(db.Integer, default=0)
    ranking = db.Column(db.Integer, default=0)
    language = db.Column(db.String(10))
    edited_at = db.Column(db.DateTime)

    ap_id = db.Column(db.String(255), index=True)

    search_vector = db.Column(TSVectorType('body'))


class Domain(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), index=True)
    post_count = db.Column(db.Integer, default=0)
    banned = db.Column(db.Boolean, default=False, index=True)


class DomainBlock(db.Model):
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), primary_key=True)
    domain_id = db.Column(db.Integer, db.ForeignKey('domain.id'), primary_key=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class CommunityBlock(db.Model):
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), primary_key=True)
    community_id = db.Column(db.Integer, db.ForeignKey('community.id'), primary_key=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class CommunityMember(db.Model):
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), primary_key=True)
    community_id = db.Column(db.Integer, db.ForeignKey('community.id'), primary_key=True)
    is_moderator = db.Column(db.Boolean, default=False)
    is_owner = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# people banned from communities
class CommunityBan(db.Model):
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), primary_key=True)
    community_id = db.Column(db.Integer, db.ForeignKey('community.id'), primary_key=True)
    banned_by = db.Column(db.Integer, db.ForeignKey('user.id'))
    reason = db.Column(db.String(50))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    ban_until = db.Column(db.DateTime)


class UserNote(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    target_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    body = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class UserBlock(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    blocker_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    blocked_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class BannedInstances(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    domain = db.Column(db.String(256), index=True)
    reason = db.Column(db.String(256))
    initiator = db.Column(db.String(256))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Instance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    domain = db.Column(db.String(256), index=True)
    inbox = db.Column(db.String(256))
    shared_inbox = db.Column(db.String(256))
    outbox = db.Column(db.String(256))


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


# save every activity to a log, to aid debugging
class ActivityPubLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    direction = db.Column(db.String(3))         # 'in' or 'out'
    activity_id = db.Column(db.String(100), indexed=True)
    activity_type = db.Column(db.String(50))    # e.g. 'Follow', 'Accept', 'Like', etc
    activity_json = db.Column(db.Text)          # the full json of the activity
    result = db.Column(db.String(10))           # 'success' or 'failure'
    exception_message = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


@login.user_loader
def load_user(id):
    return User.query.get(int(id))
