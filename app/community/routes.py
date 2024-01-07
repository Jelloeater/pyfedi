from flask import redirect, url_for, flash, request, make_response, session, Markup, current_app, abort, g, json
from flask_login import current_user, login_required
from flask_babel import _
from sqlalchemy import or_, desc

from app import db, constants, cache
from app.activitypub.signature import RsaKeys, post_request
from app.activitypub.util import default_context, notify_about_post
from app.community.forms import SearchRemoteCommunity, AddLocalCommunity, CreatePostForm, ReportCommunityForm, \
    DeleteCommunityForm
from app.community.util import search_for_community, community_url_exists, actor_to_community, \
    opengraph_parse, url_to_thumbnail_file, save_post, save_icon_file, save_banner_file, send_to_remote_instance
from app.constants import SUBSCRIPTION_MEMBER, SUBSCRIPTION_OWNER, POST_TYPE_LINK, POST_TYPE_ARTICLE, POST_TYPE_IMAGE, \
    SUBSCRIPTION_PENDING
from app.models import User, Community, CommunityMember, CommunityJoinRequest, CommunityBan, Post, \
    File, PostVote, utcnow, Report, Notification, InstanceBlock, ActivityPubLog
from app.community import bp
from app.utils import get_setting, render_template, allowlist_html, markdown_to_html, validation_required, \
    shorten_string, markdown_to_text, domain_from_url, validate_image, gibberish, community_membership, ap_datetime, \
    request_etag_matches, return_304, instance_banned, can_create, can_upvote, can_downvote
from feedgen.feed import FeedGenerator
from datetime import timezone, timedelta


@bp.route('/add_local', methods=['GET', 'POST'])
@login_required
def add_local():
    flash('PieFed is still being tested so hosting communities on piefed.social is not advised except for testing purposes.', 'warning')
    form = AddLocalCommunity()
    if g.site.enable_nsfw is False:
        form.nsfw.render_kw = {'disabled': True}

    if form.validate_on_submit() and not community_url_exists(form.url.data):
        # todo: more intense data validation
        if form.url.data.strip().lower().startswith('/c/'):
            form.url.data = form.url.data[3:]
        private_key, public_key = RsaKeys.generate_keypair()
        community = Community(title=form.community_name.data, name=form.url.data, description=form.description.data,
                              rules=form.rules.data, nsfw=form.nsfw.data, private_key=private_key,
                              public_key=public_key, description_html=markdown_to_html(form.description.data),
                              rules_html=markdown_to_html(form.rules.data),
                              ap_profile_id='https://' + current_app.config['SERVER_NAME'] + '/c/' + form.url.data,
                              ap_followers_url='https://' + current_app.config['SERVER_NAME'] + '/c/' + form.url.data + '/followers',
                              subscriptions_count=1, instance_id=1, low_quality='memes' in form.url.data)
        icon_file = request.files['icon_file']
        if icon_file and icon_file.filename != '':
            file = save_icon_file(icon_file)
            if file:
                community.icon = file
        banner_file = request.files['banner_file']
        if banner_file and banner_file.filename != '':
            file = save_banner_file(banner_file)
            if file:
                community.image = file
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

    # If nothing has changed since their last visit, return HTTP 304
    current_etag = f"{community.id}_{hash(community.last_active)}"
    if current_user.is_anonymous and request_etag_matches(current_etag):
        return return_304(current_etag)

    if community.banned:
        abort(404)

    page = request.args.get('page', 1, type=int)
    sort = request.args.get('sort', '')

    mods = community.moderators()

    is_moderator = current_user.is_authenticated and any(mod.user_id == current_user.id for mod in mods)
    is_owner = current_user.is_authenticated and any(
        mod.user_id == current_user.id and mod.is_owner == True for mod in mods)
    is_admin = current_user.is_authenticated and current_user.is_admin()

    if community.private_mods:
        mod_list = []
    else:
        mod_user_ids = [mod.user_id for mod in mods]
        mod_list = User.query.filter(User.id.in_(mod_user_ids)).all()

    if current_user.is_anonymous or current_user.ignore_bots:
        posts = community.posts.filter(Post.from_bot == False)
    else:
        posts = community.posts
    if sort == '' or sort == 'hot':
        posts = posts.order_by(desc(Post.ranking))
    elif sort == 'top':
        posts = posts.filter(Post.posted_at > utcnow() - timedelta(days=7)).order_by(desc(Post.score))
    elif sort == 'new':
        posts = posts.order_by(desc(Post.posted_at))
    posts = posts.paginate(page=page, per_page=100, error_out=False)

    description = shorten_string(community.description, 150) if community.description else None
    og_image = community.image.source_url if community.image_id else None

    next_url = url_for('activitypub.community_profile', actor=community.ap_id if community.ap_id is not None else community.name,
                       page=posts.next_num, sort=sort) if posts.has_next else None
    prev_url = url_for('activitypub.community_profile', actor=community.ap_id if community.ap_id is not None else community.name,
                       page=posts.prev_num, sort=sort) if posts.has_prev and page != 1 else None

    return render_template('community/community.html', community=community, title=community.title,
                           is_moderator=is_moderator, is_owner=is_owner, is_admin=is_admin, mods=mod_list, posts=posts, description=description,
                           og_image=og_image, POST_TYPE_IMAGE=POST_TYPE_IMAGE, POST_TYPE_LINK=POST_TYPE_LINK, SUBSCRIPTION_PENDING=SUBSCRIPTION_PENDING,
                           SUBSCRIPTION_MEMBER=SUBSCRIPTION_MEMBER, etag=f"{community.id}_{hash(community.last_active)}",
                           next_url=next_url, prev_url=prev_url,
                           rss_feed=f"https://{current_app.config['SERVER_NAME']}/community/{community.link()}/feed", rss_feed_name=f"{community.title} posts on PieFed")


# RSS feed of the community
@bp.route('/<actor>/feed', methods=['GET'])
@cache.cached(timeout=600)
def show_community_rss(actor):
    actor = actor.strip()
    if '@' in actor:
        community: Community = Community.query.filter_by(ap_id=actor, banned=False).first()
    else:
        community: Community = Community.query.filter_by(name=actor, banned=False, ap_id=None).first()
    if community is not None:
        # If nothing has changed since their last visit, return HTTP 304
        current_etag = f"{community.id}_{hash(community.last_active)}"
        if request_etag_matches(current_etag):
            return return_304(current_etag, 'application/rss+xml')

        posts = community.posts.filter(Post.from_bot == False).order_by(desc(Post.created_at)).limit(100).all()
        description = shorten_string(community.description, 150) if community.description else None
        og_image = community.image.source_url if community.image_id else None
        fg = FeedGenerator()
        fg.id(f"https://{current_app.config['SERVER_NAME']}/c/{actor}")
        fg.title(community.title)
        fg.link(href=f"https://{current_app.config['SERVER_NAME']}/c/{actor}", rel='alternate')
        if og_image:
            fg.logo(og_image)
        else:
            fg.logo(f"https://{current_app.config['SERVER_NAME']}/static/images/apple-touch-icon.png")
        if description:
            fg.subtitle(description)
        else:
            fg.subtitle(' ')
        fg.link(href=f"https://{current_app.config['SERVER_NAME']}/c/{actor}/feed", rel='self')
        fg.language('en')

        for post in posts:
            fe = fg.add_entry()
            fe.title(post.title)
            fe.link(href=f"https://{current_app.config['SERVER_NAME']}/post/{post.id}")
            fe.description(post.body_html)
            fe.guid(post.profile_id(), permalink=True)
            fe.author(name=post.author.user_name)
            fe.pubDate(post.created_at.replace(tzinfo=timezone.utc))

        response = make_response(fg.rss_str())
        response.headers.set('Content-Type', 'application/rss+xml')
        response.headers.add_header('ETag', f"{community.id}_{hash(community.last_active)}")
        response.headers.add_header('Cache-Control', 'no-cache, max-age=600, must-revalidate')
        return response
    else:
        abort(404)


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
                success = post_request(community.ap_inbox_url, follow, current_user.private_key,
                                                           current_user.profile_id() + '#main-key')
                if success:
                    flash(_('You have joined %(name)s', name=community.title))
                else:
                    flash(_('There was a problem while trying to join.'), 'error')
            else:  # for local communities, joining is instant
                banned = CommunityBan.query.filter_by(user_id=current_user.id, community_id=community.id).first()
                if banned:
                    flash(_('You cannot join this community'))
                else:
                    member = CommunityMember(user_id=current_user.id, community_id=community.id)
                    db.session.add(member)
                    db.session.commit()
                    flash('You joined ' + community.title)
        referrer = request.headers.get('Referer', None)
        cache.delete_memoized(community_membership, current_user, community)
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
                    undo_id = f"https://{current_app.config['SERVER_NAME']}/activities/undo/" + gibberish(15)
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
                        'id': undo_id,
                        'object': follow
                    }
                    activity = ActivityPubLog(direction='out', activity_id=undo_id, activity_type='Undo',
                                              activity_json=json.dumps(undo), result='processing')
                    db.session.add(activity)
                    db.session.commit()
                    success = post_request(community.ap_inbox_url, undo, current_user.private_key,
                                                               current_user.profile_id() + '#main-key')
                    activity.result = 'success'
                    db.session.commit()
                    if not success:
                        flash('There was a problem while trying to join', 'error')

                if proceed:
                    db.session.query(CommunityMember).filter_by(user_id=current_user.id, community_id=community.id).delete()
                    db.session.query(CommunityJoinRequest).filter_by(user_id=current_user.id, community_id=community.id).delete()
                    db.session.commit()

                    flash('You are left ' + community.title)
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
    if g.site.enable_nsfw is False:
        form.nsfw.render_kw = {'disabled': True}
    if g.site.enable_nsfl is False:
        form.nsfl.render_kw = {'disabled': True}
    if community.nsfw:
        form.nsfw.data = True
        form.nsfw.render_kw = {'disabled': True}
    if community.nsfl:
        form.nsfl.data = True
        form.nsfw.render_kw = {'disabled': True}
    images_disabled = 'disabled' if not get_setting('allow_local_image_posts', True) else ''    # bug: this will disable posting of images to *remote* hosts too

    form.communities.choices = [(c.id, c.display_name()) for c in current_user.communities()]

    if not can_create(current_user, community):
        abort(401)

    if form.validate_on_submit():
        community = Community.query.get_or_404(form.communities.data)
        if not can_create(current_user, community):
            abort(401)
        post = Post(user_id=current_user.id, community_id=form.communities.data, instance_id=1)
        save_post(form, post)
        community.post_count += 1
        community.last_active = g.site.last_active = utcnow()
        db.session.commit()
        post.ap_id = f"https://{current_app.config['SERVER_NAME']}/post/{post.id}"
        db.session.commit()

        notify_about_post(post)

        page = {
            'type': 'Page',
            'id': post.ap_id,
            'attributedTo': current_user.ap_profile_id,
            'to': [
                community.ap_profile_id,
                'https://www.w3.org/ns/activitystreams#Public'
            ],
            'name': post.title,
            'cc': [],
            'content': post.body_html,
            'mediaType': 'text/html',
            'source': {
                'content': post.body,
                'mediaType': 'text/markdown'
            },
            'attachment': [],
            'commentsEnabled': post.comments_enabled,
            'sensitive': post.nsfw,
            'nsfl': post.nsfl,
            'published': ap_datetime(utcnow()),
            'audience': community.ap_profile_id
        }
        create = {
            "id": f"https://{current_app.config['SERVER_NAME']}/activities/create/{gibberish(15)}",
            "actor": current_user.ap_profile_id,
            "to": [
                "https://www.w3.org/ns/activitystreams#Public"
            ],
            "cc": [
                community.ap_profile_id
            ],
            "type": "Create",
            "audience": community.ap_profile_id,
            "object": page,
            '@context': default_context()
        }
        if post.type == POST_TYPE_LINK:
            page.attachment = [{'href': post.url, 'type': 'Link'}]
        if post.image_id:
            page.image = [{'type': 'Image', 'url': post.image.source_url}]
        if not community.is_local():  # this is a remote community - send the post to the instance that hosts it
            success = post_request(community.ap_inbox_url, create, current_user.private_key,
                                   current_user.ap_profile_id + '#main-key')
            if success:
                flash(_('Your post to %(name)s has been made.', name=community.title))
            else:
                flash('There was a problem making your post to ' + community.title)
        else:   # local community - send (announce) post out to followers
            announce = {
                "id": f"https://{current_app.config['SERVER_NAME']}/activities/announce/{gibberish(15)}",
                "type": 'Announce',
                "to": [
                    "https://www.w3.org/ns/activitystreams#Public"
                ],
                "actor": community.ap_profile_id,
                "cc": [
                    community.ap_followers_url
                ],
                '@context': default_context(),
                'object': create
            }

            sent_to = 0
            for instance in community.following_instances():
                if instance.inbox and not current_user.has_blocked_instance(instance.id) and not instance_banned(instance.domain):
                    send_to_remote_instance(instance.id, community.id, announce)
                    sent_to += 1
            if sent_to:
                flash(_('Your post to %(name)s has been made.', name=community.title))
            else:
                flash(_('Your post to %(name)s has been made.', name=community.title))

        return redirect(f"/c/{community.link()}")
    else:
        form.communities.data = community.id
        form.notify_author.data = True

    return render_template('community/add_post.html', title=_('Add post to community'), form=form, community=community,
                           images_disabled=images_disabled, markdown_editor=True)


@bp.route('/community/<int:community_id>/report', methods=['GET', 'POST'])
@login_required
def community_report(community_id: int):
    community = Community.query.get_or_404(community_id)
    form = ReportCommunityForm()
    if form.validate_on_submit():
        report = Report(reasons=form.reasons_to_string(form.reasons.data), description=form.description.data,
                        type=1, reporter_id=current_user.id, suspect_community_id=community.id)
        db.session.add(report)

        # Notify admin
        # todo: find all instance admin(s). for now just load User.id == 1
        admins = [User.query.get_or_404(1)]
        for admin in admins:
            notification = Notification(user_id=admin.id, title=_('A community has been reported'),
                                            url=community.local_url(),
                                            author_id=current_user.id)
            db.session.add(notification)
            admin.unread_notifications += 1
        db.session.commit()

        # todo: federate report to originating instance
        if not community.is_local() and form.report_remote.data:
            ...

        flash(_('Community has been reported, thank you!'))
        return redirect(community.local_url())

    return render_template('community/community_report.html', title=_('Report community'), form=form, community=community)


@bp.route('/community/<int:community_id>/delete', methods=['GET', 'POST'])
@login_required
def community_delete(community_id: int):
    community = Community.query.get_or_404(community_id)
    if community.is_owner() or current_user.is_admin():
        form = DeleteCommunityForm()
        if form.validate_on_submit():
            if community.is_local():
                community.banned = True
                # todo: federate deletion out to all instances. At end of federation process, delete_dependencies() and delete community
            else:
                community.delete_dependencies()
                db.session.delete(community)
            db.session.commit()
            flash(_('Community deleted'))
            return redirect('/communities')

        return render_template('community/community_delete.html', title=_('Delete community'), form=form,
                               community=community)
    else:
        abort(401)


@bp.route('/community/<int:community_id>/block_instance', methods=['GET', 'POST'])
@login_required
def community_block_instance(community_id: int):
    community = Community.query.get_or_404(community_id)
    existing = InstanceBlock.query.filter_by(user_id=current_user.id, instance_id=community.instance_id).first()
    if not existing:
        db.session.add(InstanceBlock(user_id=current_user.id, instance_id=community.instance_id))
        db.session.commit()
    flash(_('Content from %(name)s will be hidden.', name=community.instance.domain))
    return redirect(community.local_url())


@bp.route('/<int:community_id>/notification', methods=['GET', 'POST'])
@login_required
def community_notification(community_id: int):
    community = Community.query.get_or_404(community_id)
    member_info = CommunityMember.query.filter(CommunityMember.community_id == community.id,
                                               CommunityMember.user_id == current_user.id).first()
    # existing community members get their notification flag toggled
    if member_info and not member_info.is_banned:
        member_info.notify_new_posts = not member_info.notify_new_posts
        db.session.commit()
    else:   # people who are not yet members become members, with notify on.
        if not community.user_is_banned(current_user):
            new_member = CommunityMember(community_id=community.id, user_id=current_user.id, notify_new_posts=True)
            db.session.add(new_member)
            db.session.commit()

    return render_template('community/_notification_toggle.html', community=community)
