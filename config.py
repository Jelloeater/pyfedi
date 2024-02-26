import os
from dotenv import load_dotenv

basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(basedir, '.env'))


class Config(object):
    SERVER_NAME = os.environ.get('SERVER_NAME') or 'localhost'
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'you-will-never-guesss'
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
                              'sqlite:///' + os.path.join(basedir, 'app.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    MAIL_SERVER = os.environ.get('MAIL_SERVER')
    MAIL_PORT = int(os.environ.get('MAIL_PORT') or 25)
    MAIL_USE_TLS = os.environ.get('MAIL_USE_TLS') is not None
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD')
    RECAPTCHA_PUBLIC_KEY = os.environ.get("RECAPTCHA_PUBLIC_KEY")
    RECAPTCHA_PRIVATE_KEY = os.environ.get("RECAPTCHA_PRIVATE_KEY")
    MODE = os.environ.get('MODE') or 'development'
    LANGUAGES = ['en']
    FULL_AP_CONTEXT = os.environ.get('FULL_AP_CONTEXT') or True
    CACHE_TYPE = os.environ.get('CACHE_TYPE') or 'FileSystemCache'
    CACHE_REDIS_URL = os.environ.get('CACHE_REDIS_URL') or 'redis://localhost:6379/1'
    CACHE_DIR = os.environ.get('CACHE_DIR') or '/dev/shm/pyfedi'
    CACHE_DEFAULT_TIMEOUT = 300
    CACHE_THRESHOLD = 1000
    CACHE_KEY_PREFIX = 'pyfedi'
    CELERY_BROKER_URL = os.environ.get('CELERY_BROKER_URL') or 'redis://localhost:6379/0'
    RESULT_BACKEND = os.environ.get('RESULT_BACKEND') or 'redis://localhost:6379/0'
    SQLALCHEMY_ECHO = False     # set to true to see SQL in console
    WTF_CSRF_TIME_LIMIT = None  # a value of None ensures csrf token is valid for the lifetime of the session

    BOUNCE_HOST = os.environ.get('BOUNCE_HOST') or ''
    BOUNCE_USERNAME = os.environ.get('BOUNCE_USERNAME') or ''
    BOUNCE_PASSWORD = os.environ.get('BOUNCE_PASSWORD') or ''

