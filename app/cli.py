# if commands in this file are not working (e.g. 'flask translate') make sure you set the FLASK_APP environment variable.
# e.g. export FLASK_APP=pyfedi.py
from flask import json

from app import db
import click
import os

from app.models import Settings, BannedInstances, Interest
from app.utils import file_get_contents


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
            db.session.append(Settings(name='allow_nsfw', value=json.dumps(False)))
            db.session.append(Settings(name='allow_dislike', value=json.dumps(True)))
            db.session.append(BannedInstances(domain='lemmygrad.ml'))
            db.session.append(BannedInstances(domain='gab.com'))
            db.session.append(BannedInstances(domain='exploding-heads.com'))
            db.session.append(BannedInstances(domain='hexbear.net'))
            db.session.append(BannedInstances(domain='threads.net'))
            interests = file_get_contents('interests.txt')
            db.session.append(Interest(name='🕊 Chilling', communities=parse_communities(interests, 'chilling')))
            db.session.append(Interest(name='💭 Interesting stuff', communities=parse_communities(interests, 'interesting stuff')))
            db.session.append(Interest(name='📰 News & Politics', communities=parse_communities(interests, 'news & politics')))
            db.session.append(Interest(name='🎮 Gaming', communities=parse_communities(interests, 'gaming')))
            db.session.append(Interest(name='🤓 Linux', communities=parse_communities(interests, 'linux')))
            db.session.append(Interest(name='♻️ Environment', communities=parse_communities(interests, 'environment')))
            db.session.append(Interest(name='🏳‍🌈 LGBTQ+', communities=parse_communities(interests, 'lgbtq')))
            db.session.append(Interest(name='🛠 Programming', communities=parse_communities(interests, 'programming')))
            db.session.append(Interest(name='🖥️ Tech', communities=parse_communities(interests, 'tech')))
            db.session.append(Interest(name='🤗 Mental Health', communities=parse_communities(interests, 'mental health')))
            db.session.commit()
            print("Done")


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
