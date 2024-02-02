# if commands in this file are not working (e.g. 'flask translate') make sure you set the FLASK_APP environment variable.
# e.g. export FLASK_APP=pyfedi.py
from datetime import datetime, timedelta

from flask import json

from app import db
import click
import os

from app.activitypub.signature import RsaKeys
from app.auth.util import random_token
from app.email import send_verification_email
from app.models import Settings, BannedInstances, Interest, Role, User, RolePermission, Domain, ActivityPubLog, \
    utcnow, Site, Instance
from app.utils import file_get_contents, retrieve_block_list


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
            admin_user = User(user_name=user_name, email=email, verification_token=verification_token)
            admin_user.set_password(password)
            admin_user.roles.append(admin_role)
            send_verification_email(admin_user)
            print("Check your email inbox for a verification link.")

            db.session.commit()
            print("Initial setup is finished.")

    @app.cli.command('daily-maintenance')
    def daily_maintenance():
        with app.app_context():
            """Remove activity older than 3 days"""
            db.session.query(ActivityPubLog).filter(
                ActivityPubLog.created_at < utcnow() - timedelta(days=3)).delete()
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
