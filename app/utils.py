import functools

import requests
import os

from flask import current_app, json

from app import db
from app.models import Settings


# ----------------------------------------------------------------------
# Jinja: when a file was modified. Useful for cache-busting
def getmtime(filename):
    return os.path.getmtime('static/' + filename)


# do a GET request to a uri, return the result
def get_request(uri, params=None, headers=None) -> requests.Response:
    try:
        response = requests.get(uri, params=params, headers=headers, timeout=1, allow_redirects=True)
    except requests.exceptions.SSLError as invalid_cert:
        # Not our problem if the other end doesn't have proper SSL
        current_app.logger.info(f"{uri} {invalid_cert}")
        raise requests.exceptions.SSLError from invalid_cert
    except ValueError as ex:
        # Convert to a more generic error we handle
        raise requests.exceptions.RequestException(f"InvalidCodepoint: {str(ex)}") from None

    return response


@functools.lru_cache(maxsize=100)
def get_setting(name: str, default=None):
    setting = Settings.query.filter_by(name=name).first()
    if setting is None:
        return default
    else:
        return json.loads(setting.value)


def set_setting(name: str, value):
    setting = Settings.query.filter_by(name=name).first()
    if setting is None:
        db.session.append(Settings(name=name, value=json.dumps(value)))
    else:
        setting.value = json.dumps(value)
    db.session.commit()
    get_setting.cache_clear()