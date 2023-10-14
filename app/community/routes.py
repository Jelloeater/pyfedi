from datetime import date, datetime, timedelta

from flask import redirect, url_for, flash, request, make_response, session, Markup, current_app, abort
from flask_login import login_user, logout_user, current_user, login_required
from flask_babel import _
from sqlalchemy import or_

from app import db
from app.activitypub.signature import RsaKeys, HttpSignature
from app.community.forms import SearchRemoteCommunity, AddLocalCommunity, CreatePost, NewReplyForm
from app.community.util import search_for_community, community_url_exists, actor_to_community, post_replies
from app.constants import SUBSCRIPTION_MEMBER, SUBSCRIPTION_OWNER, POST_TYPE_LINK, POST_TYPE_ARTICLE, POST_TYPE_IMAGE
from app.models import User, Community, CommunityMember, CommunityJoinRequest, CommunityBan, Post, PostReply, \
    PostReplyVote
from app.community import bp
from app.utils import get_setting, render_template, allowlist_html, markdown_to_html


@bp.route('/add_local', methods=['GET', 'POST'])
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
    mods = community.moderators()

    is_moderator = current_user.is_authenticated and any(mod.user_id == current_user.id for mod in mods)
    is_owner = current_user.is_authenticated and any(mod.user_id == current_user.id and mod.is_owner == True for mod in mods)

    if community.private_mods:
        mod_list = []
    else:
        mod_user_ids = [mod.user_id for mod in mods]
        mod_list = User.query.filter(User.id.in_(mod_user_ids)).all()

    if current_user.ignore_bots:
        posts = community.posts.filter(Post.from_bot == False).all()
    else:
        posts = community.posts

    return render_template('community/community.html', community=community, title=community.title,
                           is_moderator=is_moderator, is_owner=is_owner, mods=mod_list, posts=posts)


@bp.route('/<actor>/subscribe', methods=['GET'])
@login_required
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
                    "id": f"https://{current_app.config['SERVER_NAME']}/activities/follow/{join_request.id}"
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
@login_required
def unsubscribe(actor):
    community = actor_to_community(actor)

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


@bp.route('/<actor>/submit', methods=['GET', 'POST'])
@login_required
def add_post(actor):
    community = actor_to_community(actor)
    form = CreatePost()
    if get_setting('allow_nsfw', False) is False:
        form.nsfw.render_kw = {'disabled': True}
    if get_setting('allow_nsfl', False) is False:
        form.nsfl.render_kw = {'disabled': True}
    images_disabled = 'disabled' if not get_setting('allow_local_image_posts', True) else ''

    form.communities.choices = [(c.id, c.display_name()) for c in current_user.communities()]

    if form.validate_on_submit():
        post = Post(user_id=current_user.id, community_id=form.communities.data, nsfw=form.nsfw.data,
                    nsfl=form.nsfl.data)
        if form.type.data == '' or form.type.data == 'discussion':
            post.title = form.discussion_title.data
            post.body = form.discussion_body.data
            post.body_html = markdown_to_html(post.body)
            post.type = POST_TYPE_ARTICLE
        elif form.type.data == 'link':
            post.title = form.link_title.data
            post.url = form.link_url.data
            post.type = POST_TYPE_LINK
        elif form.type.data == 'image':
            post.title = form.image_title.data
            post.type = POST_TYPE_IMAGE
            # todo: handle file upload
        elif form.type.data == 'poll':
            ...
        else:
            raise Exception('invalid post type')
        db.session.add(post)
        community.post_count += 1
        db.session.commit()

        # todo: federate post creation out to followers

        flash('Post has been added')
        return redirect(f"/c/{community.link()}")
    else:
        form.communities.data = community.id
        form.notify.data = True

    return render_template('community/add_post.html', title=_('Add post to community'), form=form, community=community,
                           images_disabled=images_disabled)


@bp.route('/post/<int:post_id>', methods=['GET', 'POST'])
def show_post(post_id: int):
    post = Post.query.get_or_404(post_id)
    mods = post.community.moderators()
    is_moderator = current_user.is_authenticated and any(mod.user_id == current_user.id for mod in mods)
    form = NewReplyForm()
    if form.validate_on_submit():
        reply = PostReply(user_id=current_user.id, post_id=post.id, community_id=post.community.id, body=form.body.data,
                          body_html=markdown_to_html(form.body.data), body_html_safe=True,
                          from_bot=current_user.bot, up_votes=1, nsfw=post.nsfw, nsfl=post.nsfl)
        db.session.add(reply)
        db.session.commit()
        reply_vote = PostReplyVote(user_id=current_user.id, author_id=current_user.id, post_reply_id=reply.id,
                                   effect=1.0)
        db.session.add(reply_vote)
        db.session.commit()
        form.body.data = ''
        flash('Your comment has been added.')
        # todo: flush cache
        # todo: federation
        return redirect(url_for('community.show_post', post_id=post_id))    # redirect to current page to avoid refresh resubmitting the form
    else:
        replies = post_replies(post.id, 'top')
    return render_template('community/post.html', title=post.title, post=post, is_moderator=is_moderator,
                           canonical=post.ap_id, form=form, replies=replies)


@bp.route('/comment/<int:comment_id>/<vote_direction>', methods=['POST'])
def comment_vote(comment_id, vote_direction):
    upvoted_class = downvoted_class = ''
    comment = PostReply.query.get_or_404(comment_id)
    existing_vote = PostReplyVote.query.filter_by(user_id=current_user.id, post_reply_id=comment.id).first()
    if existing_vote:
        if existing_vote.effect > 0:        # previous vote was up
            if vote_direction == 'upvote':  # new vote is also up, so remove it
                db.session.delete(existing_vote)
                comment.up_votes -= 1
                comment.score -= 1
            else:                           # new vote is down while previous vote was up, so reverse their previous vote
                existing_vote.effect = -1
                comment.up_votes -= 1
                comment.down_votes += 1
                comment.score -= 2
                downvoted_class = 'voted_down'
        else:                               # previous vote was down
            if vote_direction == 'upvote':  # new vote is upvote
                existing_vote.effect = 1
                comment.up_votes += 1
                comment.down_votes -= 1
                comment.score += 1
                upvoted_class = 'voted_up'
            else:                           # reverse a previous downvote
                db.session.delete(existing_vote)
                comment.down_votes -= 1
                comment.score += 2
    else:
        if vote_direction == 'upvote':
            effect = 1
            comment.up_votes += 1
            comment.score += 1
            upvoted_class = 'voted_up'
        else:
            effect = -1
            comment.down_votes += 1
            comment.score -= 1
            downvoted_class = 'voted_down'
        vote = PostReplyVote(user_id=current_user.id, post_reply_id=comment_id, author_id=comment.user_id, effect=effect)
        db.session.add(vote)
    db.session.commit()
    return render_template('community/_voting_buttons.html', comment=comment,
                           upvoted_class=upvoted_class,
                           downvoted_class=downvoted_class)
