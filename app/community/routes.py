from flask import redirect, url_for, flash, request, make_response, session, Markup, current_app, abort
from flask_login import login_user, logout_user, current_user, login_required
from flask_babel import _
from pillow_heif import register_heif_opener
from sqlalchemy import or_, desc

from app import db, constants, cache
from app.activitypub.signature import RsaKeys, HttpSignature
from app.activitypub.util import default_context
from app.community.forms import SearchRemoteCommunity, AddLocalCommunity, CreatePostForm
from app.community.util import search_for_community, community_url_exists, actor_to_community, \
    ensure_directory_exists, opengraph_parse, url_to_thumbnail_file, save_post
from app.constants import SUBSCRIPTION_MEMBER, SUBSCRIPTION_OWNER, POST_TYPE_LINK, POST_TYPE_ARTICLE, POST_TYPE_IMAGE, \
    SUBSCRIPTION_PENDING
from app.models import User, Community, CommunityMember, CommunityJoinRequest, CommunityBan, Post, \
    File, PostVote
from app.community import bp
from app.utils import get_setting, render_template, allowlist_html, markdown_to_html, validation_required, \
    shorten_string, markdown_to_text, domain_from_url, validate_image, gibberish, community_membership
import os
from PIL import Image, ImageOps
from datetime import datetime


@bp.route('/add_local', methods=['GET', 'POST'])
@login_required
def add_local():
    form = AddLocalCommunity()
    if get_setting('allow_nsfw', False) is False:
        form.nsfw.render_kw = {'disabled': True}

    if form.validate_on_submit() and not community_url_exists(form.url.data):
        # todo: more intense data validation
        if form.url.data.strip().lower().startswith('/c/'):
            form.url.data = form.url.data[3:]
        private_key, public_key = RsaKeys.generate_keypair()
        community = Community(title=form.community_name.data, name=form.url.data, description=form.description.data,
                              rules=form.rules.data, nsfw=form.nsfw.data, private_key=private_key,
                              public_key=public_key,
                              ap_profile_id=current_app.config['SERVER_NAME'] + '/c/' + form.url.data,
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
@login_required
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
                           subscribed=community_membership(current_user, new_community) >= SUBSCRIPTION_MEMBER)


# @bp.route('/c/<actor>', methods=['GET']) - defined in activitypub/routes.py, which calls this function for user requests. A bit weird.
def show_community(community: Community):
    mods = community.moderators()

    is_moderator = current_user.is_authenticated and any(mod.user_id == current_user.id for mod in mods)
    is_owner = current_user.is_authenticated and any(
        mod.user_id == current_user.id and mod.is_owner == True for mod in mods)

    if community.private_mods:
        mod_list = []
    else:
        mod_user_ids = [mod.user_id for mod in mods]
        mod_list = User.query.filter(User.id.in_(mod_user_ids)).all()

    if current_user.is_anonymous or current_user.ignore_bots:
        posts = community.posts.filter(Post.from_bot == False).order_by(desc(Post.last_active)).all()
    else:
        posts = community.posts.order_by(desc(Post.last_active)).all()

    description = shorten_string(community.description, 150) if community.description else None
    og_image = community.image.source_url if community.image_id else None

    return render_template('community/community.html', community=community, title=community.title,
                           is_moderator=is_moderator, is_owner=is_owner, mods=mod_list, posts=posts, description=description,
                           og_image=og_image, POST_TYPE_IMAGE=POST_TYPE_IMAGE, POST_TYPE_LINK=POST_TYPE_LINK, SUBSCRIPTION_PENDING=SUBSCRIPTION_PENDING,
                           SUBSCRIPTION_MEMBER=SUBSCRIPTION_MEMBER)


@bp.route('/<actor>/subscribe', methods=['GET'])
@login_required
@validation_required
def subscribe(actor):
    remote = False
    actor = actor.strip()
    if '@' in actor:
        community = Community.query.filter_by(banned=False, ap_id=actor).first()
        remote = True
    else:
        community = Community.query.filter_by(name=actor, banned=False, ap_id=None).first()

    if community is not None:
        if community_membership(current_user, community) != SUBSCRIPTION_MEMBER and community_membership(current_user, community) != SUBSCRIPTION_PENDING:
            if remote:
                # send ActivityPub message to remote community, asking to follow. Accept message will be sent to our shared inbox
                join_request = CommunityJoinRequest(user_id=current_user.id, community_id=community.id)
                db.session.add(join_request)
                db.session.commit()
                follow = {
                    "actor": f"https://{current_app.config['SERVER_NAME']}/u/{current_user.user_name}",
                    "to": [community.ap_profile_id],
                    "object": community.ap_profile_id,
                    "type": "Follow",
                    "id": f"https://{current_app.config['SERVER_NAME']}/activities/follow/{join_request.id}"
                }
                try:
                    message = HttpSignature.signed_request(community.ap_inbox_url, follow, current_user.private_key,
                                                           current_user.profile_id() + '#main-key')
                    if message.status_code == 200:
                        flash('Your request to subscribe has been sent to ' + community.title)
                    else:
                        flash('Response status code was not 200', 'warning')
                        current_app.logger.error('Response code for subscription attempt was ' +
                                                 str(message.status_code) + ' ' + message.text)
                except Exception as ex:
                    flash('Failed to send request to subscribe: ' + str(ex), 'error')
                    current_app.logger.error("Exception while trying to subscribe" + str(ex))
            else:  # for local communities, joining is instant
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
@login_required
def unsubscribe(actor):
    community = actor_to_community(actor)

    if community is not None:
        subscription = community_membership(current_user, community)
        if subscription:
            if subscription != SUBSCRIPTION_OWNER:
                proceed = True
                # Undo the Follow
                if '@' in actor:    # this is a remote community, so activitypub is needed
                    follow = {
                        "actor": f"https://{current_app.config['SERVER_NAME']}/u/{current_user.user_name}",
                        "to": [community.ap_profile_id],
                        "object": community.ap_profile_id,
                        "type": "Follow",
                        "id": f"https://{current_app.config['SERVER_NAME']}/activities/follow/{gibberish(15)}"
                    }
                    undo = {
                        'actor': current_user.profile_id(),
                        'to': [community.ap_profile_id],
                        'type': 'Undo',
                        'id': f"https://{current_app.config['SERVER_NAME']}/activities/undo/" + gibberish(15),
                        'object': follow
                    }
                    try:
                        message = HttpSignature.signed_request(community.ap_inbox_url, undo, current_user.private_key,
                                                               current_user.profile_id() + '#main-key')
                        if message.status_code != 200:
                            flash('Response status code was not 200', 'warning')
                            current_app.logger.error('Response code for unsubscription attempt was ' +
                                                     str(message.status_code) + ' ' + message.text)
                            proceed = False
                    except Exception as ex:
                        proceed = False
                        flash('Failed to send request to unsubscribe: ' + str(ex), 'error')
                        current_app.logger.error("Exception while trying to unsubscribe" + str(ex))
                if proceed:
                    db.session.query(CommunityMember).filter_by(user_id=current_user.id, community_id=community.id).delete()
                    db.session.query(CommunityJoinRequest).filter_by(user_id=current_user.id, community_id=community.id).delete()
                    db.session.commit()

                    flash('You are unsubscribed from ' + community.title)
                cache.delete_memoized(community_membership, current_user, community)

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


@bp.route('/<actor>/submit', methods=['GET', 'POST'])
@login_required
@validation_required
def add_post(actor):
    community = actor_to_community(actor)
    form = CreatePostForm()
    if get_setting('allow_nsfw', False) is False:
        form.nsfw.render_kw = {'disabled': True}
    if get_setting('allow_nsfl', False) is False:
        form.nsfl.render_kw = {'disabled': True}
    images_disabled = 'disabled' if not get_setting('allow_local_image_posts', True) else ''

    form.communities.choices = [(c.id, c.display_name()) for c in current_user.communities()]

    if form.validate_on_submit():
        post = Post(user_id=current_user.id, community_id=form.communities.data)
        save_post(form, post)
        community.post_count += 1
        community.last_active = datetime.utcnow()
        db.session.commit()


        # todo: federate post creation out to followers

        flash('Post has been added')
        return redirect(f"/c/{community.link()}")
    else:
        form.communities.data = community.id
        form.notify_author.data = True

    return render_template('community/add_post.html', title=_('Add post to community'), form=form, community=community,
                           images_disabled=images_disabled)



