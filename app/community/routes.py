from datetime import date, datetime, timedelta
from flask import render_template, redirect, url_for, flash, request, make_response, session, Markup, current_app
from flask_login import login_user, logout_user, current_user
from flask_babel import _
from app import db
from app.activitypub.signature import RsaKeys
from app.community.forms import SearchRemoteCommunity, AddLocalCommunity
from app.community.util import search_for_community
from app.constants import SUBSCRIPTION_MEMBER
from app.models import User, Community, CommunityMember
from app.community import bp
from app.utils import get_setting


@bp.route('/add_local', methods=['GET', 'POST'])
def add_local():
    form = AddLocalCommunity()
    if get_setting('allow_nsfw', False) is False:
        form.nsfw.render_kw = {'disabled': True}

    if form.validate_on_submit():
        private_key, public_key = RsaKeys.generate_keypair()
        community = Community(title=form.community_name.data, name=form.url.data, description=form.description.data,
                              rules=form.rules.data, nsfw=form.nsfw.data, private_key=private_key, public_key=public_key,
                              subscriptions_count=1)
        db.session.add(community)
        db.session.commit()
        membership = CommunityMember(user_id=current_user.id, community_id=community.id, is_moderator=True,
                                     is_owner=True)
        db.session.add(membership)
        db.session.commit()
        flash(_('Your new community has been created.'))
        return redirect('/c/' + community.name)

    return render_template('community/add_local.html', title=_('Create community'), form=form)


@bp.route('/add_remote', methods=['GET', 'POST'])
def add_remote():
    form = SearchRemoteCommunity()
    new_community = None
    if form.validate_on_submit():
        address = form.address.data.strip()
        if address.startswith('!') and '@' in address:
            new_community = search_for_community(address)
        elif address.startswith('@') and '@' in address[1:]:
            # todo: the user is searching for a person instead
            ...
        elif '@' in address:
            new_community = search_for_community('!' + address)
        else:
            message = Markup('Type address in the format !community@server.name. Search on <a href="https://lemmyverse.net/communities">Lemmyverse.net</a> to find some.')
            flash(message, 'error')

    return render_template('community/add_remote.html',
                           title=_('Add remote community'), form=form, new_community=new_community,
                           subscribed=current_user.subscribed(new_community) >= SUBSCRIPTION_MEMBER)


# @bp.route('/c/<actor>', methods=['GET']) - defined in activitypub/routes.py, which calls this function for user requests. A bit weird.
def show_community(community: Community):
    return render_template('community/community.html', community=community, title=community.title)
