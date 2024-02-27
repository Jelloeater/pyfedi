# if commands in this file are not working (e.g. 'flask translate') make sure you set the FLASK_APP environment variable.
# e.g. export FLASK_APP=pyfedi.py
import imaplib
import re
from datetime import datetime, timedelta

import flask
from flask import json, current_app
from flask_babel import _
from sqlalchemy import or_, desc

from app import db
import click
import os

from app.activitypub.signature import RsaKeys
from app.auth.util import random_token
from app.email import send_verification_email, send_email
from app.models import Settings, BannedInstances, Interest, Role, User, RolePermission, Domain, ActivityPubLog, \
    utcnow, Site, Instance, File, Notification, Post, CommunityMember
from app.utils import file_get_contents, retrieve_block_list, blocked_domains


def register(app):
    @app.cli.group()
    def translate():
        """Translation and localization commands."""
        pass

    @translate.command()
    @click.argument('lang')
    def init(lang):
        """Initialize a new language."""
        if os.system('pybabel extract -F babel.cfg -k _l -o messages.pot .'):
            raise RuntimeError('extract command failed')
        if os.system(
                'pybabel init -i messages.pot -d app/translations -l ' + lang):
            raise RuntimeError('init command failed')
        os.remove('messages.pot')

    @translate.command()
    def update():
        """Update all languages."""
        if os.system('pybabel extract -F babel.cfg -k _l -o messages.pot .'):
            raise RuntimeError('extract command failed')
        if os.system('pybabel update -i messages.pot -d app/translations'):
            raise RuntimeError('update command failed')
        os.remove('messages.pot')

    @translate.command()
    def compile():
        """Compile all languages."""
        if os.system('pybabel compile -d app/translations'):
            raise RuntimeError('compile command failed')

    @app.cli.command("init-db")
    def init_db():
        with app.app_context():
            db.drop_all()
            db.configure_mappers()
            db.create_all()
            private_key, public_key = RsaKeys.generate_keypair()
            db.session.add(Site(name="PieFed", description='', public_key=public_key, private_key=private_key))
            db.session.add(Instance(domain=app.config['SERVER_NAME'], software='PieFed'))   # Instance 1 is always the local instance
            db.session.add(Settings(name='allow_nsfw', value=json.dumps(False)))
            db.session.add(Settings(name='allow_nsfl', value=json.dumps(False)))
            db.session.add(Settings(name='allow_dislike', value=json.dumps(True)))
            db.session.add(Settings(name='allow_local_image_posts', value=json.dumps(True)))
            db.session.add(Settings(name='allow_remote_image_posts', value=json.dumps(True)))
            db.session.add(Settings(name='registration_open', value=json.dumps(True)))
            db.session.add(Settings(name='approve_registrations', value=json.dumps(False)))
            db.session.add(Settings(name='federation', value=json.dumps(True)))
            db.session.add(BannedInstances(domain='lemmygrad.ml'))
            db.session.add(BannedInstances(domain='gab.com'))
            db.session.add(BannedInstances(domain='rqd2.net'))
            db.session.add(BannedInstances(domain='exploding-heads.com'))
            db.session.add(BannedInstances(domain='hexbear.net'))
            db.session.add(BannedInstances(domain='threads.net'))
            db.session.add(BannedInstances(domain='pieville.net'))
            db.session.add(BannedInstances(domain='noauthority.social'))
            db.session.add(BannedInstances(domain='pieville.net'))
            db.session.add(BannedInstances(domain='links.hackliberty.org'))
            interests = file_get_contents('interests.txt')
            db.session.add(Interest(name='🕊 Chilling', communities=parse_communities(interests, 'chilling')))
            db.session.add(Interest(name='💭 Interesting stuff', communities=parse_communities(interests, 'interesting stuff')))
            db.session.add(Interest(name='📰 News & Politics', communities=parse_communities(interests, 'news & politics')))
            db.session.add(Interest(name='🎮 Gaming', communities=parse_communities(interests, 'gaming')))
            db.session.add(Interest(name='🤓 Linux', communities=parse_communities(interests, 'linux')))
            db.session.add(Interest(name='♻️ Environment', communities=parse_communities(interests, 'environment')))
            db.session.add(Interest(name='🏳‍🌈 LGBTQ+', communities=parse_communities(interests, 'lgbtq')))
            db.session.add(Interest(name='🛠 Programming', communities=parse_communities(interests, 'programming')))
            db.session.add(Interest(name='🖥️ Tech', communities=parse_communities(interests, 'tech')))
            db.session.add(Interest(name='🤗 Mental Health', communities=parse_communities(interests, 'mental health')))
            db.session.add(Interest(name='💊 Health', communities=parse_communities(interests, 'health')))

            # Load initial domain block list
            block_list = retrieve_block_list()
            if block_list:
                for domain in block_list.split('\n'):
                    db.session.add(Domain(name=domain.strip(), banned=True))

            # Initial roles
            anon_role = Role(name='Anonymous user', weight=0)
            anon_role.permissions.append(RolePermission(permission='register'))
            db.session.add(anon_role)

            auth_role = Role(name='Authenticated user', weight=1)
            db.session.add(auth_role)

            staff_role = Role(name='Staff', weight=2)
            staff_role.permissions.append(RolePermission(permission='approve registrations'))
            staff_role.permissions.append(RolePermission(permission='ban users'))
            staff_role.permissions.append(RolePermission(permission='administer all communities'))
            staff_role.permissions.append(RolePermission(permission='administer all users'))
            db.session.add(staff_role)

            admin_role = Role(name='Admin', weight=3)
            admin_role.permissions.append(RolePermission(permission='approve registrations'))
            admin_role.permissions.append(RolePermission(permission='change user roles'))
            admin_role.permissions.append(RolePermission(permission='ban users'))
            admin_role.permissions.append(RolePermission(permission='manage users'))
            admin_role.permissions.append(RolePermission(permission='change instance settings'))
            admin_role.permissions.append(RolePermission(permission='administer all communities'))
            admin_role.permissions.append(RolePermission(permission='administer all users'))
            db.session.add(admin_role)

            # Admin user
            user_name = input("Admin user name (ideally not 'admin'): ")
            email = input("Admin email address: ")
            password = input("Admin password: ")
            verification_token = random_token(16)
            private_key, public_key = RsaKeys.generate_keypair()
            admin_user = User(user_name=user_name, title=user_name,
                              email=email, verification_token=verification_token,
                              instance_id=1, email_unread_sent=False,
                              private_key=private_key, public_key=public_key)
            admin_user.set_password(password)
            admin_user.roles.append(admin_role)
            admin_user.verified = True
            admin_user.last_seen = utcnow()
            admin_user.ap_profile_id = f"https://{current_app.config['SERVER_NAME']}/u/{admin_user.user_name}"
            admin_user.ap_public_url = f"https://{current_app.config['SERVER_NAME']}/u/{admin_user.user_name}"
            admin_user.ap_inbox_url = f"https://{current_app.config['SERVER_NAME']}/u/{admin_user.user_name}/inbox"
            db.session.add(admin_user)

            db.session.commit()
            print("Initial setup is finished.")

    @app.cli.command('daily-maintenance')
    def daily_maintenance():
        with app.app_context():
            """Remove activity older than 3 days"""
            db.session.query(ActivityPubLog).filter(ActivityPubLog.created_at < utcnow() - timedelta(days=3)).delete()
            db.session.commit()

    @app.cli.command("spaceusage")
    def spaceusage():
        with app.app_context():
            for user in User.query.all():
                filesize = user.filesize()
                num_content = user.num_content()
                if filesize > 0 and num_content > 0:
                    print(f'{user.id},"{user.ap_id}",{filesize},{num_content}')

    def list_files(directory):
        for root, dirs, files in os.walk(directory):
            for file in files:
                yield os.path.join(root, file)

    @app.cli.command("remove_orphan_files")
    def remove_orphan_files():
        """ Any user-uploaded file that does not have a corresponding entry in the File table should be deleted """
        with app.app_context():
            for file_path in list_files('app/static/media/users'):
                if 'thumbnail' in file_path:
                    f = File.query.filter(File.thumbnail_path == file_path).first()
                else:
                    f = File.query.filter(File.file_path == file_path).first()
                if f is None:
                    os.unlink(file_path)

    @app.cli.command("send_missed_notifs")
    def send_missed_notifs():
        with app.app_context():
            users_to_notify = User.query.join(Notification, User.id == Notification.user_id).filter(
                User.ap_id == None,
                Notification.created_at > User.last_seen,
                Notification.read == False,
                User.email_unread_sent == False,  # they have not been emailed since last activity
                User.email_unread == True  # they want to be emailed
            ).all()

            for user in users_to_notify:
                notifications = Notification.query.filter(Notification.user_id == user.id, Notification.read == False,
                                                          Notification.created_at > user.last_seen).all()
                if notifications:
                    # Also get the top 20 posts since their last login
                    posts = Post.query.join(CommunityMember, Post.community_id == CommunityMember.community_id).filter(
                        CommunityMember.is_banned == False)
                    posts = posts.filter(CommunityMember.user_id == user.id)
                    if user.ignore_bots:
                        posts = posts.filter(Post.from_bot == False)
                    if user.show_nsfl is False:
                        posts = posts.filter(Post.nsfl == False)
                    if user.show_nsfw is False:
                        posts = posts.filter(Post.nsfw == False)
                    domains_ids = blocked_domains(user.id)
                    if domains_ids:
                        posts = posts.filter(or_(Post.domain_id.not_in(domains_ids), Post.domain_id == None))
                    posts = posts.filter(Post.posted_at > user.last_seen).order_by(desc(Post.score))
                    posts = posts.limit(20).all()

                    # Send email!
                    send_email(_('[PieFed] You have unread notifications'),
                               sender=f'PieFed <noreply@{current_app.config["SERVER_NAME"]}>',
                               recipients=[user.email],
                               text_body=flask.render_template('email/unread_notifications.txt', user=user,
                                                               notifications=notifications),
                               html_body=flask.render_template('email/unread_notifications.html', user=user,
                                                               notifications=notifications,
                                                               posts=posts,
                                                               domain=current_app.config['SERVER_NAME']))
                    user.email_unread_sent = True
                    db.session.commit()

    @app.cli.command("process_email_bounces")
    def process_email_bounces():
        with app.app_context():
            import email

            imap_host = current_app.config['BOUNCE_HOST']
            imap_user = current_app.config['BOUNCE_USERNAME']
            imap_pass = current_app.config['BOUNCE_PASSWORD']
            something_deleted = False

            if imap_host:

                # connect to host using SSL
                imap = imaplib.IMAP4_SSL(imap_host, port=993)

                ## login to server
                imap.login(imap_user, imap_pass)

                imap.select('Inbox')

                tmp, data = imap.search(None, 'ALL')
                rgx = r'[\w\.-]+@[\w\.-]+'

                emails = set()

                for num in data[0].split():
                    tmp, data = imap.fetch(num, '(RFC822)')
                    email_message = email.message_from_bytes(data[0][1])
                    match = []
                    if not isinstance(email_message._payload, str):
                        if isinstance(email_message._payload[0]._payload, str):
                            payload = email_message._payload[0]._payload.replace("\n", " ").replace("\r", " ")
                            match = re.findall(rgx, payload)
                        elif isinstance(email_message._payload[0]._payload, list):
                            if isinstance(email_message._payload[0]._payload[0]._payload, str):
                                payload = email_message._payload[0]._payload[0]._payload.replace("\n", " ").replace("\r", " ")
                                match = re.findall(rgx, payload)

                        for m in match:
                            if current_app.config['SERVER_NAME'] not in m and current_app.config['SERVER_NAME'].upper() not in m:
                                emails.add(m)
                                print(str(num) + ' ' + m)

                    imap.store(num, '+FLAGS', '\\Deleted')
                    something_deleted = True

                if something_deleted:
                    imap.expunge()
                    pass

                imap.close()

                # Keep track of how many times email to an account has bounced. After 2 bounces, disable email sending to them
                for bounced_email in emails:
                    bounced_accounts = User.query.filter_by(email=bounced_email).all()
                    for account in bounced_accounts:
                        if account.bounces is None:
                            account.bounces = 0
                        if account.bounces > 2:
                            account.newsletter = False
                            account.email_unread = False
                        else:
                            account.bounces += 1
                    db.session.commit()


def parse_communities(interests_source, segment):
    lines = interests_source.split("\n")
    include_in_output = False
    output = []

    for line in lines:
        line = line.strip()
        if line == segment:
            include_in_output = True
            continue
        elif line == '':
            include_in_output = False
        if include_in_output:
            output.append(line)

    return "\n".join(output)
