from __future__ import annotations

import random
from datetime import datetime
from typing import List, Literal

import markdown2
import math
from urllib.parse import urlparse
import requests
from functools import wraps
import flask
from bs4 import BeautifulSoup
import requests
import os
import imghdr
from flask import current_app, json, redirect, url_for, request, make_response, Response
from flask_login import current_user
from sqlalchemy import text
from wtforms.fields  import SelectField, SelectMultipleField
from wtforms.widgets import Select, html_params, ListWidget, CheckboxInput
from app import db, cache

from app.models import Settings, Domain, Instance, BannedInstances, User, Community, DomainBlock, ActivityPubLog


# Flask's render_template function, with support for themes added
def render_template(template_name: str, **context) -> Response:
    theme = get_setting('theme', '')
    if theme != '':
        content = flask.render_template(f'themes/{theme}/{template_name}', **context)
    else:
        content = flask.render_template(template_name, **context)

    # Browser caching using ETags and Cache-Control
    resp = make_response(content)
    if current_user.is_anonymous:
        if 'etag' in context:
            resp.headers.add_header('ETag', context['etag'])
        resp.headers.add_header('Cache-Control', 'no-cache, max-age=600, must-revalidate')
    return resp


def request_etag_matches(etag):
    if 'If-None-Match' in request.headers:
        old_etag = request.headers['If-None-Match']
        return old_etag == etag
    return False


def return_304(etag, content_type=None):
    resp = make_response('', 304)
    resp.headers.add_header('ETag', request.headers['If-None-Match'])
    resp.headers.add_header('Cache-Control', 'no-cache, max-age=600, must-revalidate')
    if content_type:
        resp.headers.set('Content-Type', content_type)
    return resp


# Jinja: when a file was modified. Useful for cache-busting
def getmtime(filename):
    return os.path.getmtime('static/' + filename)


# do a GET request to a uri, return the result
def get_request(uri, params=None, headers=None) -> requests.Response:
    if headers is None:
        headers = {'User-Agent': 'PieFed/1.0'}
    else:
        headers.update({'User-Agent': 'PieFed/1.0'})
    try:
        response = requests.get(uri, params=params, headers=headers, timeout=5, allow_redirects=True)
    except requests.exceptions.SSLError as invalid_cert:
        # Not our problem if the other end doesn't have proper SSL
        current_app.logger.info(f"{uri} {invalid_cert}")
        raise requests.exceptions.SSLError from invalid_cert
    except ValueError as ex:
        # Convert to a more generic error we handle
        raise requests.exceptions.RequestException(f"InvalidCodepoint: {str(ex)}") from None
    except requests.exceptions.ReadTimeout as read_timeout:
        current_app.logger.info(f"{uri} {read_timeout}")
        raise requests.exceptions.ReadTimeout from read_timeout

    return response


# do a HEAD request to a uri, return the result
def head_request(uri, params=None, headers=None) -> requests.Response:
    if headers is None:
        headers = {'User-Agent': 'PieFed/1.0'}
    else:
        headers.update({'User-Agent': 'PieFed/1.0'})
    try:
        response = requests.head(uri, params=params, headers=headers, timeout=5, allow_redirects=True)
    except requests.exceptions.SSLError as invalid_cert:
        # Not our problem if the other end doesn't have proper SSL
        current_app.logger.info(f"{uri} {invalid_cert}")
        raise requests.exceptions.SSLError from invalid_cert
    except ValueError as ex:
        # Convert to a more generic error we handle
        raise requests.exceptions.RequestException(f"InvalidCodepoint: {str(ex)}") from None
    except requests.exceptions.ReadTimeout as read_timeout:
        current_app.logger.info(f"{uri} {read_timeout}")
        raise requests.exceptions.ReadTimeout from read_timeout

    return response


# saves an arbitrary object into a persistent key-value store. cached.
@cache.memoize(timeout=50)
def get_setting(name: str, default=None):
    setting = Settings.query.filter_by(name=name).first()
    if setting is None:
        return default
    else:
        return json.loads(setting.value)


# retrieves arbitrary object from persistent key-value store
def set_setting(name: str, value):
    setting = Settings.query.filter_by(name=name).first()
    if setting is None:
        db.session.add(Settings(name=name, value=json.dumps(value)))
    else:
        setting.value = json.dumps(value)
    db.session.commit()
    cache.delete_memoized(get_setting)


# Return the contents of a file as a string. Inspired by PHP's function of the same name.
def file_get_contents(filename):
    with open(filename, 'r') as file:
        contents = file.read()
    return contents


random_chars = '0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ'


def gibberish(length: int = 10) -> str:
    return "".join([random.choice(random_chars) for x in range(length)])


def is_image_url(url):
    parsed_url = urlparse(url)
    path = parsed_url.path.lower()
    common_image_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.webp']
    return any(path.endswith(extension) for extension in common_image_extensions)


# sanitise HTML using an allow list
def allowlist_html(html: str) -> str:
    allowed_tags = ['p', 'strong', 'a', 'ul', 'ol', 'li', 'em', 'blockquote', 'cite', 'br', 'h3', 'h4', 'h5', 'pre',
                    'code']
    # Parse the HTML using BeautifulSoup
    soup = BeautifulSoup(html, 'html.parser')

    # Find all tags in the parsed HTML
    for tag in soup.find_all():
        # If the tag is not in the allowed_tags list, remove it and its contents
        if tag.name not in allowed_tags:
            tag.extract()
        else:
            # Filter and sanitize attributes
            for attr in list(tag.attrs):
                if attr not in ['href', 'src']:  # Add allowed attributes here
                    del tag[attr]

    # Encode the HTML to prevent script execution
    return str(soup)


# convert basic HTML to Markdown
def html_to_markdown(html: str) -> str:
    soup = BeautifulSoup(html, 'html.parser')
    return html_to_markdown_worker(soup)


def html_to_markdown_worker(element, indent_level=0):
    formatted_text = ''
    for item in element.contents:
        if isinstance(item, str):
            formatted_text += item
        elif item.name == 'p':
            formatted_text += '\n\n'
        elif item.name == 'br':
            formatted_text += '  \n'  # Double space at the end for line break
        elif item.name == 'strong':
            formatted_text += '**' + html_to_markdown_worker(item) + '**'
        elif item.name == 'ul':
            formatted_text += '\n'
            formatted_text += html_to_markdown_worker(item, indent_level + 1)
            formatted_text += '\n'
        elif item.name == 'ol':
            formatted_text += '\n'
            formatted_text += html_to_markdown_worker(item, indent_level + 1)
            formatted_text += '\n'
        elif item.name == 'li':
            bullet = '-' if item.find_parent(['ul', 'ol']) and item.find_previous_sibling() is None else ''
            formatted_text += '  ' * indent_level + bullet + ' ' + html_to_markdown_worker(item).strip() + '\n'
        elif item.name == 'blockquote':
            formatted_text += '  ' * indent_level + '> ' + html_to_markdown_worker(item).strip() + '\n'
        elif item.name == 'code':
            formatted_text += '`' + html_to_markdown_worker(item) + '`'
    return formatted_text


def markdown_to_html(markdown_text) -> str:
    if markdown_text:
        return allowlist_html(markdown2.markdown(markdown_text, safe_mode=True))
    else:
        return ''


def markdown_to_text(markdown_text) -> str:
    if not markdown_text or markdown_text == '':
        return ''
    return markdown_text.replace("# ", '')


def domain_from_url(url: str, create=True) -> Domain:
    parsed_url = urlparse(url.lower().replace('www.', ''))
    domain = Domain.query.filter_by(name=parsed_url.hostname.lower()).first()
    if create and domain is None:
        domain = Domain(name=parsed_url.hostname.lower())
        db.session.add(domain)
        db.session.commit()
    return domain


def shorten_string(input_str, max_length=50):
    if len(input_str) <= max_length:
        return input_str
    else:
        return input_str[:max_length - 3] + '…'


def shorten_url(input: str, max_length=20):
    return shorten_string(input.replace('https://', '').replace('http://', ''))


# the number of digits in a number. e.g. 1000 would be 4
def digits(input: int) -> int:
    if input == 0:
        return 1  # Special case: 0 has 1 digit
    else:
        return math.floor(math.log10(abs(input))) + 1


@cache.memoize(timeout=50)
def user_access(permission: str, user_id: int) -> bool:
    has_access = db.session.execute(text('SELECT * FROM "role_permission" as rp ' +
                                    'INNER JOIN user_role ur on rp.role_id = ur.role_id ' +
                                    'WHERE ur.user_id = :user_id AND rp.permission = :permission'),
                                    {'user_id': user_id, 'permission': permission}).first()
    return has_access is not None


@cache.memoize(timeout=86400)
def community_membership(user: User, community: Community) -> int:
    # @cache.memoize works with User.subscribed but cache.delete_memoized does not, making it bad to use on class methods.
    # however cache.memoize and cache.delete_memoized works fine with normal functions
    if community is None:
        return False
    return user.subscribed(community.id)


@cache.memoize(timeout=86400)
def blocked_domains(user_id) -> List[int]:
    blocks = DomainBlock.query.filter_by(user_id=user_id)
    return [block.domain_id for block in blocks]


def retrieve_block_list():
    try:
        response = requests.get('https://github.com/rimu/no-qanon/blob/master/domains.txt', timeout=1)
    except:
        return None
    if response and response.status_code == 200:
        return response.text


def ensure_directory_exists(directory):
    parts = directory.split('/')
    rebuild_directory = ''
    for part in parts:
        rebuild_directory += part
        if not os.path.isdir(rebuild_directory):
            os.mkdir(rebuild_directory)
        rebuild_directory += '/'


def validate_image(stream):
        header = stream.read(512)
        stream.seek(0)
        format = imghdr.what(None, header)
        if not format:
            return None
        return '.' + (format if format != 'jpeg' else 'jpg')


def validation_required(func):
    @wraps(func)
    def decorated_view(*args, **kwargs):
        if current_user.verified:
            return func(*args, **kwargs)
        else:
            return redirect(url_for('auth.validation_required'))
    return decorated_view


def permission_required(permission):
    def decorator(func):
        @wraps(func)
        def decorated_view(*args, **kwargs):
            if user_access(permission, current_user.id):
                return func(*args, **kwargs)
            else:
                # Handle the case where the user doesn't have the required permission
                return redirect(url_for('auth.permission_denied'))

        return decorated_view

    return decorator


# sends the user back to where they came from
def back(default_url):
    # Get the referrer from the request headers
    referrer = request.referrer

    # If the referrer exists and is not the same as the current request URL, redirect to the referrer
    if referrer and referrer != request.url:
        return redirect(referrer)

    # If referrer is not available or is the same as the current request URL, redirect to the default URL
    return redirect(default_url)


# format a datetime in a way that is used in ActivityPub
def ap_datetime(date_time: datetime) -> str:
    return date_time.isoformat() + '+00:00'


class MultiCheckboxField(SelectMultipleField):
    widget = ListWidget(prefix_label=False)
    option_widget = CheckboxInput()