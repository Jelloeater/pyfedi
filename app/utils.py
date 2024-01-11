from __future__ import annotations

import random
from collections import defaultdict
from datetime import datetime, timedelta, date
from typing import List, Literal, Union

import markdown2
import math
from urllib.parse import urlparse
from functools import wraps
import flask
from bs4 import BeautifulSoup, NavigableString
import requests
import os
import imghdr
from flask import current_app, json, redirect, url_for, request, make_response, Response, g
from flask_login import current_user
from sqlalchemy import text, or_
from wtforms.fields  import SelectField, SelectMultipleField
from wtforms.widgets import Select, html_params, ListWidget, CheckboxInput
from app import db, cache
import re

from app.models import Settings, Domain, Instance, BannedInstances, User, Community, DomainBlock, ActivityPubLog, IpBan, \
    Site, Post, PostReply, utcnow, Filter


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
    if html is None or html == '':
        return ''
    allowed_tags = ['p', 'strong', 'a', 'ul', 'ol', 'li', 'em', 'blockquote', 'cite', 'br', 'h3', 'h4', 'h5', 'pre',
                    'code', 'img']
    # Parse the HTML using BeautifulSoup
    soup = BeautifulSoup(html, 'html.parser')

    # Find all plain text links, convert to <a> tags
    re_url = re.compile(r'(http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\(\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+)')
    for tag in soup.find_all(text=True):
        tags = []
        url = False
        for t in re_url.split(tag.string):
            if re_url.match(t):
                a = soup.new_tag("a", href=t)
                a.string = t
                tags.append(a)
                url = True
            else:
                tags.append(t)
        if url:
            for t in tags:
                tag.insert_before(t)
            tag.extract()

    # Filter tags, leaving only safe ones
    for tag in soup.find_all():
        # If the tag is not in the allowed_tags list, remove it and its contents
        if tag.name not in allowed_tags:
            tag.extract()
        else:
            # Filter and sanitize attributes
            for attr in list(tag.attrs):
                if attr not in ['href', 'src', 'alt']:
                    del tag[attr]
            # Add nofollow and target=_blank to anchors
            if tag.name == 'a':
                tag.attrs['rel'] = 'nofollow ugc'
                tag.attrs['target'] = '_blank'

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
    return len(shorten_number(input))


@cache.memoize(timeout=50)
def user_access(permission: str, user_id: int) -> bool:
    has_access = db.session.execute(text('SELECT * FROM "role_permission" as rp ' +
                                    'INNER JOIN user_role ur on rp.role_id = ur.role_id ' +
                                    'WHERE ur.user_id = :user_id AND rp.permission = :permission'),
                                    {'user_id': user_id, 'permission': permission}).first()
    return has_access is not None


@cache.memoize(timeout=10)
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
        response = requests.get('https://raw.githubusercontent.com/rimu/no-qanon/master/domains.txt', timeout=1)
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


def ip_address() -> str:
    ip = request.headers.get('X-Forwarded-For') or request.remote_addr
    if ',' in ip:  # Remove all but first ip addresses
        ip = ip[:ip.index(',')].strip()
    return ip


def user_ip_banned() -> bool:
    current_ip_address = ip_address()
    if current_ip_address:
        return current_ip_address in banned_ip_addresses()


@cache.memoize(timeout=30)
def instance_banned(domain: str) -> bool:   # see also activitypub.util.instance_blocked()
    banned = BannedInstances.query.filter_by(domain=domain).first()
    return banned is not None


def user_cookie_banned() -> bool:
    cookie = request.cookies.get('sesion', None)
    return cookie is not None


@cache.memoize(timeout=300)
def banned_ip_addresses() -> List[str]:
    ips = IpBan.query.all()
    return [ip.ip_address for ip in ips]


def can_downvote(user, community: Community, site=None) -> bool:
    if user is None or community is None or user.banned:
        return False

    if site is None:
        try:
            site = g.site
        except:
            site = Site.query.get(1)

    if not site.enable_downvotes and community.is_local():
        return False

    if community.local_only and not user.is_local():
        return False

    if user.attitude < -0.40 or user.reputation < -10:  # this should exclude about 3.7% of users.
        return False

    return True


def can_upvote(user, community: Community) -> bool:
    if user is None or community is None or user.banned:
        return False

    return True


def can_create(user, content: Union[Community, Post, PostReply]) -> bool:
    if user is None or content is None or user.banned:
        return False

    if isinstance(content, Community):
        if content.is_moderator(user) or user.is_admin():
            return True

        if content.restricted_to_mods:
            return False

        if content.local_only and not user.is_local():
            return False
    else:
        if content.community.is_moderator(user) or user.is_admin():
            return True

        if content.community.restricted_to_mods and isinstance(content, Post):
            return False

        if content.community.local_only and not user.is_local():
            return False

        if isinstance(content, PostReply) and content.post.comments_enabled is False:
            return False

    return True


def reply_already_exists(user_id, post_id, parent_id, body) -> bool:
    if parent_id is None:
        num_matching_replies = db.session.execute(text(
            'SELECT COUNT(id) as c FROM "post_reply" WHERE user_id = :user_id AND post_id = :post_id AND parent_id is null AND body = :body'),
            {'user_id': user_id, 'post_id': post_id, 'body': body}).scalar()
    else:
        num_matching_replies = db.session.execute(text(
            'SELECT COUNT(id) as c FROM "post_reply" WHERE user_id = :user_id AND post_id = :post_id AND parent_id = :parent_id AND body = :body'),
            {'user_id': user_id, 'post_id': post_id, 'parent_id': parent_id, 'body': body}).scalar()
    return num_matching_replies != 0


def reply_is_just_link_to_gif_reaction(body) -> bool:
    tmp_body = body.strip()
    if tmp_body.startswith('https://media.tenor.com/') or \
            tmp_body.startswith('https://i.giphy.com/') or \
            tmp_body.startswith('https://i.imgflip.com') or \
            tmp_body.startswith('https://media1.giphy.com/') or \
            tmp_body.startswith('https://media2.giphy.com/') or \
            tmp_body.startswith('https://media3.giphy.com/') or \
            tmp_body.startswith('https://media4.giphy.com/'):
        return True
    else:
        return False


def inbox_domain(inbox: str) -> str:
    inbox = inbox.lower()
    if 'https://' in inbox or 'http://' in inbox:
        inbox = urlparse(inbox).hostname
    return inbox


def awaken_dormant_instance(instance):
    if instance and not instance.gone_forever:
        if instance.dormant:
            if instance.start_trying_again < utcnow():
                instance.dormant = False
                db.session.commit()
        # give up after ~5 days of trying
        if instance.start_trying_again and utcnow() + timedelta(days=5) < instance.start_trying_again:
            instance.gone_forever = True
            instance.dormant = True
            db.session.commit()


def shorten_number(number):
    if number < 1000:
        return str(number)
    elif number < 1000000:
        return f'{number / 1000:.1f}k'
    else:
        return f'{number / 1000000:.1f}M'


@cache.memoize(timeout=300)
def user_filters_home(user_id):
    filters = Filter.query.filter_by(user_id=user_id, filter_home=True).filter(or_(Filter.expire_after > date.today(), Filter.expire_after == None))
    result = defaultdict(set)
    for filter in filters:
        keywords = [keyword.strip().lower() for keyword in filter.keywords.splitlines()]
        if filter.hide_type == 0:
            result[filter.title].update(keywords)
        else:   # type == 1 means hide completely. These posts are excluded from output by the jinja template
            result['-1'].update(keywords)
    return result


@cache.memoize(timeout=300)
def user_filters_posts(user_id):
    filters = Filter.query.filter_by(user_id=user_id, filter_posts=True).filter(or_(Filter.expire_after > date.today(), Filter.expire_after == None))
    result = defaultdict(set)
    for filter in filters:
        keywords = [keyword.strip().lower() for keyword in filter.keywords.splitlines()]
        if filter.hide_type == 0:
            result[filter.title].update(keywords)
        else:
            result['-1'].update(keywords)
    return result


@cache.memoize(timeout=300)
def user_filters_replies(user_id):
    filters = Filter.query.filter_by(user_id=user_id, filter_replies=True).filter(or_(Filter.expire_after > date.today(), Filter.expire_after == None))
    result = defaultdict(set)
    for filter in filters:
        keywords = [keyword.strip().lower() for keyword in filter.keywords.splitlines()]
        if filter.hide_type == 0:
            result[filter.title].update(keywords)
        else:
            result['-1'].update(keywords)
    return result


# All the following post/comment ranking math is explained at https://medium.com/hacking-and-gonzo/how-reddit-ranking-algorithms-work-ef111e33d0d9
epoch = datetime(1970, 1, 1)

def epoch_seconds(date):
    td = date - epoch
    return td.days * 86400 + td.seconds + (float(td.microseconds) / 1000000)


def post_ranking(score, date: datetime):
    if date is None:
        date = datetime.utcnow()
    if score is None:
        score = 1
    order = math.log(max(abs(score), 1), 10)
    sign = 1 if score > 0 else -1 if score < 0 else 0
    seconds = epoch_seconds(date) - 1685766018
    return round(sign * order + seconds / 45000, 7)


# used for ranking comments
def _confidence(ups, downs):
    n = ups + downs

    if n == 0:
        return 0.0

    z = 1.281551565545
    p = float(ups) / n

    left = p + 1 / (2 * n) * z * z
    right = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    under = 1 + 1 / n * z * z

    return (left - right) / under


def confidence(ups, downs) -> float:
    if ups + downs == 0:
        return 0.0
    else:
        return _confidence(ups, downs)
