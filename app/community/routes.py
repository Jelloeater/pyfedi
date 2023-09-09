from datetime import date, datetime, timedelta
from flask import render_template, redirect, url_for, flash, request, make_response, session, Markup, current_app, abort
from flask_login import login_user, logout_user, current_user
from flask_babel import _
from app import db
from app.activitypub.signature import RsaKeys, HttpSignature
from app.community.forms import SearchRemoteCommunity, AddLocalCommunity
from app.community.util import search_for_community, community_url_exists
from app.constants import SUBSCRIPTION_MEMBER, SUBSCRIPTION_OWNER
from app.models import User, Community, CommunityMember, CommunityJoinRequest, CommunityBan
from app.community import bp
from app.utils import get_setting
from sqlalchemy import or_


@bp.route('/add_local', methods=['GET', 'POST'])
def add_local():
    form = AddLocalCommunity()
    if get_setting('allow_nsfw', False) is False:
        form.nsfw.render_kw = {'disabled': True}

    if form.validate_on_submit() and not community_url_exists(form.url.data):
        # todo: more intense data validation
        if form.url.data.trim().lower().startswith('/c/'):
            form.url.data = form.url.data[3:]
        private_key, public_key = RsaKeys.generate_keypair()
        community = Community(title=form.community_name.data, name=form.url.data, description=form.description.data,
                              rules=form.rules.data, nsfw=form.nsfw.data, private_key=private_key,
                              public_key=public_key, ap_profile_id=current_app.config['SERVER_NAME'] + '/c/' + form.url.data,
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
            message = Markup(
                'Type address in the format !community@server.name. Search on <a href="https://lemmyverse.net/communities">Lemmyverse.net</a> to find some.')
            flash(message, 'error')

    return render_template('community/add_remote.html',
                           title=_('Add remote community'), form=form, new_community=new_community,
                           subscribed=current_user.subscribed(new_community) >= SUBSCRIPTION_MEMBER)


# @bp.route('/c/<actor>', methods=['GET']) - defined in activitypub/routes.py, which calls this function for user requests. A bit weird.
def show_community(community: Community):
    mods = CommunityMember.query.filter((CommunityMember.community_id == community.id) &
                                        (or_(
                                            CommunityMember.is_owner,
                                            CommunityMember.is_moderator
                                        ))
                                        ).all()

    is_moderator = any(mod.user_id == current_user.id for mod in mods)
    is_owner = any(mod.user_id == current_user.id and mod.is_owner == True for mod in mods)

    if community.private_mods:
        mod_list = []
    else:
        mod_user_ids = [mod.user_id for mod in mods]
        mod_list = User.query.filter(User.id.in_(mod_user_ids)).all()

    return render_template('community/community.html', community=community, title=community.title,
                           is_moderator=is_moderator, is_owner=is_owner, mods=mod_list)


@bp.route('/<actor>/subscribe', methods=['GET'])
def subscribe(actor):
    remote = False
    actor = actor.strip()
    if '@' in actor:
        community = Community.query.filter_by(banned=False, ap_id=actor).first()
        remote = True
    else:
        community = Community.query.filter_by(name=actor, banned=False, ap_id=None).first()

    if community is not None:
        if not current_user.subscribed(community):
            if remote:
                # send ActivityPub message to remote community, asking to follow. Accept message will be sent to our shared inbox
                join_request = CommunityJoinRequest(user_id=current_user.id, community_id=community.id)
                db.session.add(join_request)
                db.session.commit()
                follow = {
                    "actor": f"https://{current_app.config['SERVER_NAME']}/u/{current_user.user_name}",
                    "to": [community.ap_id],
                    "object": community.ap_id,
                    "type": "Follow",
                    "id": f"https://{current_app.config['SERVER_NAME']}/activities/follow/" + join_request.id
                }
                try:
                    message = HttpSignature.signed_request(community.ap_inbox_url, follow, current_user.private_key,
                                                           current_user.ap_profile_id + '#main-key')
                    if message.status_code == 200:
                        flash('Your request to subscribe has been sent to ' + community.title)
                    else:
                        flash('Response status code was not 200', 'warning')
                        current_app.logger.error('Response code for subscription attempt was ' +
                                                 str(message.status_code) + ' ' + message.text)
                except Exception as ex:
                    flash('Failed to send request to subscribe: ' + str(ex), 'error')
                    current_app.logger.error("Exception while trying to subscribe" + str(ex))
            else:   # for local communities, joining is instant
                banned = CommunityBan.query.filter_by(user_id=current_user.id, community_id=community.id).first()
                if banned:
                    flash('You cannot join this community')
                member = CommunityMember(user_id=current_user.id, community_id=community.id)
                db.session.add(member)
                db.session.commit()
                flash('You are subscribed to ' + community.title)
        referrer = request.headers.get('Referer', None)
        if referrer is not None:
            return redirect(referrer)
        else:
            return redirect('/c/' + actor)
    else:
        abort(404)


@bp.route('/<actor>/unsubscribe', methods=['GET'])
def unsubscribe(actor):
    actor = actor.strip()
    if '@' in actor:
        community = Community.query.filter_by(banned=False, ap_id=actor).first()
    else:
        community = Community.query.filter_by(name=actor, banned=False, ap_id=None).first()

    if community is not None:
        subscription = current_user.subscribed(community)
        if subscription:
            if subscription != SUBSCRIPTION_OWNER:
                db.session.query(CommunityMember).filter_by(user_id=current_user.id, community_id=community.id).delete()
                db.session.commit()
                flash('You are unsubscribed from ' + community.title)
            else:
                # todo: community deletion
                flash('You need to make someone else the owner before unsubscribing.', 'warning')

        # send them back where they came from
        referrer = request.headers.get('Referer', None)
        if referrer is not None:
            return redirect(referrer)
        else:
            return redirect('/c/' + actor)
    else:
        abort(404)
