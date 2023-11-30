from datetime import datetime

from flask import redirect, url_for, flash, request, make_response, session, Markup, current_app, abort
from flask_login import login_user, logout_user, current_user, login_required
from flask_babel import _
from sqlalchemy import or_, desc

from app import db, constants
from app.community.util import save_post
from app.post.forms import NewReplyForm
from app.community.forms import CreatePostForm
from app.post.util import post_replies, get_comment_branch, post_reply_count
from app.constants import SUBSCRIPTION_MEMBER, SUBSCRIPTION_OWNER, POST_TYPE_LINK, POST_TYPE_ARTICLE, POST_TYPE_IMAGE
from app.models import Post, PostReply, \
    PostReplyVote, PostVote, Notification
from app.post import bp
from app.utils import get_setting, render_template, allowlist_html, markdown_to_html, validation_required, \
    shorten_string, markdown_to_text, domain_from_url, validate_image, gibberish


@bp.route('/post/<int:post_id>', methods=['GET', 'POST'])
def show_post(post_id: int):
    post = Post.query.get_or_404(post_id)
    mods = post.community.moderators()
    is_moderator = current_user.is_authenticated and any(mod.user_id == current_user.id for mod in mods)
    form = NewReplyForm()
    if current_user.is_authenticated and current_user.verified and form.validate_on_submit():
        reply = PostReply(user_id=current_user.id, post_id=post.id, community_id=post.community.id, body=form.body.data,
                          body_html=markdown_to_html(form.body.data), body_html_safe=True,
                          from_bot=current_user.bot, up_votes=1, nsfw=post.nsfw, nsfl=post.nsfl,
                          notify_author=form.notify_author.data)
        if post.notify_author and current_user.id != post.user_id:    # todo: check if replier is blocked
            notification = Notification(title=_('Reply: ') + shorten_string(form.body.data), user_id=post.user_id,
                                        author_id=current_user.id, url=url_for('post.show_post', post_id=post.id))
            db.session.add(notification)
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
        return redirect(url_for('post.show_post',
                                post_id=post_id))  # redirect to current page to avoid refresh resubmitting the form
    else:
        replies = post_replies(post.id, 'top')
        form.notify_author.data = True

    og_image = post.image.source_url if post.image_id else None
    description = shorten_string(markdown_to_text(post.body), 150) if post.body else None

    return render_template('post/post.html', title=post.title, post=post, is_moderator=is_moderator,
                           canonical=post.ap_id, form=form, replies=replies, THREAD_CUTOFF_DEPTH=constants.THREAD_CUTOFF_DEPTH,
                           description=description, og_image=og_image, POST_TYPE_IMAGE=constants.POST_TYPE_IMAGE,
                           POST_TYPE_LINK=constants.POST_TYPE_LINK, POST_TYPE_ARTICLE=constants.POST_TYPE_ARTICLE)


@bp.route('/post/<int:post_id>/<vote_direction>', methods=['GET', 'POST'])
@login_required
@validation_required
def post_vote(post_id: int, vote_direction):
    upvoted_class = downvoted_class = ''
    post = Post.query.get_or_404(post_id)
    existing_vote = PostVote.query.filter_by(user_id=current_user.id, post_id=post.id).first()
    if existing_vote:
        post.author.reputation -= existing_vote.effect
        if existing_vote.effect > 0:  # previous vote was up
            if vote_direction == 'upvote':  # new vote is also up, so remove it
                db.session.delete(existing_vote)
                post.up_votes -= 1
                post.score -= 1
            else:  # new vote is down while previous vote was up, so reverse their previous vote
                existing_vote.effect = -1
                post.up_votes -= 1
                post.down_votes += 1
                post.score -= 2
                downvoted_class = 'voted_down'
        else:  # previous vote was down
            if vote_direction == 'upvote':  # new vote is upvote
                existing_vote.effect = 1
                post.up_votes += 1
                post.down_votes -= 1
                post.score += 1
                upvoted_class = 'voted_up'
            else:  # reverse a previous downvote
                db.session.delete(existing_vote)
                post.down_votes -= 1
                post.score += 2
    else:
        if vote_direction == 'upvote':
            effect = 1
            post.up_votes += 1
            post.score += 1
            upvoted_class = 'voted_up'
        else:
            effect = -1
            post.down_votes += 1
            post.score -= 1
            downvoted_class = 'voted_down'
        vote = PostVote(user_id=current_user.id, post_id=post.id, author_id=post.author.id,
                             effect=effect)
        post.author.reputation += effect
        db.session.add(vote)
    db.session.commit()
    return render_template('post/_post_voting_buttons.html', post=post,
                           upvoted_class=upvoted_class,
                           downvoted_class=downvoted_class)


@bp.route('/comment/<int:comment_id>/<vote_direction>', methods=['POST'])
@login_required
@validation_required
def comment_vote(comment_id, vote_direction):
    upvoted_class = downvoted_class = ''
    comment = PostReply.query.get_or_404(comment_id)
    existing_vote = PostReplyVote.query.filter_by(user_id=current_user.id, post_reply_id=comment.id).first()
    if existing_vote:
        if existing_vote.effect > 0:  # previous vote was up
            if vote_direction == 'upvote':  # new vote is also up, so remove it
                db.session.delete(existing_vote)
                comment.up_votes -= 1
                comment.score -= 1
            else:  # new vote is down while previous vote was up, so reverse their previous vote
                existing_vote.effect = -1
                comment.up_votes -= 1
                comment.down_votes += 1
                comment.score -= 2
                downvoted_class = 'voted_down'
        else:  # previous vote was down
            if vote_direction == 'upvote':  # new vote is upvote
                existing_vote.effect = 1
                comment.up_votes += 1
                comment.down_votes -= 1
                comment.score += 1
                upvoted_class = 'voted_up'
            else:  # reverse a previous downvote
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
        vote = PostReplyVote(user_id=current_user.id, post_reply_id=comment_id, author_id=comment.author.id, effect=effect)
        comment.author.reputation += effect
        db.session.add(vote)
    db.session.commit()
    return render_template('post/_voting_buttons.html', comment=comment,
                           upvoted_class=upvoted_class,
                           downvoted_class=downvoted_class)


@bp.route('/post/<int:post_id>/comment/<int:comment_id>')
def continue_discussion(post_id, comment_id):
    post = Post.query.get_or_404(post_id)
    comment = PostReply.query.get_or_404(comment_id)
    mods = post.community.moderators()
    is_moderator = current_user.is_authenticated and any(mod.user_id == current_user.id for mod in mods)
    replies = get_comment_branch(post.id, comment.id, 'top')

    return render_template('post/continue_discussion.html', title=_('Discussing %(title)s', title=post.title), post=post,
                           is_moderator=is_moderator, comment=comment, replies=replies)


@bp.route('/post/<int:post_id>/comment/<int:comment_id>/reply', methods=['GET', 'POST'])
@login_required
def add_reply(post_id: int, comment_id: int):
    post = Post.query.get_or_404(post_id)
    comment = PostReply.query.get_or_404(comment_id)
    mods = post.community.moderators()
    is_moderator = current_user.is_authenticated and any(mod.user_id == current_user.id for mod in mods)
    form = NewReplyForm()
    if form.validate_on_submit():
        reply = PostReply(user_id=current_user.id, post_id=post.id, parent_id=comment.id, depth=comment.depth + 1,
                          community_id=post.community.id, body=form.body.data,
                          body_html=markdown_to_html(form.body.data), body_html_safe=True,
                          from_bot=current_user.bot, up_votes=1, nsfw=post.nsfw, nsfl=post.nsfl,
                          notify_author=form.notify_author.data)
        db.session.add(reply)
        if comment.notify_author and current_user.id != comment.user_id:    # todo: check if replier is blocked
            notification = Notification(title=_('Reply: ') + shorten_string(form.body.data), user_id=comment.user_id,
                                        author_id=current_user.id, url=url_for('post.show_post', post_id=post.id))
            db.session.add(notification)
        db.session.commit()
        reply_vote = PostReplyVote(user_id=current_user.id, author_id=current_user.id, post_reply_id=reply.id,
                                   effect=1.0)
        db.session.add(reply_vote)
        post.reply_count = post_reply_count(post.id)
        db.session.commit()
        form.body.data = ''
        flash('Your comment has been added.')
        # todo: flush cache
        # todo: federation
        if reply.depth <= constants.THREAD_CUTOFF_DEPTH:
            return redirect(url_for('post.show_post', post_id=post_id, _anchor=f'comment_{reply.parent_id}'))
        else:
            return redirect(url_for('post.continue_discussion', post_id=post_id, comment_id=reply.parent_id))
    else:
        form.notify_author.data = True
        return render_template('post/add_reply.html', title=_('Discussing %(title)s', title=post.title), post=post,
                               is_moderator=is_moderator, form=form, comment=comment)


@bp.route('/post/<int:post_id>/options', methods=['GET'])
def post_options(post_id: int):
    post = Post.query.get_or_404(post_id)
    return render_template('post/post_options.html', post=post)

@login_required
@bp.route('/post/<int:post_id>/edit', methods=['GET', 'POST'])
def post_edit(post_id: int):
    post = Post.query.get_or_404(post_id)
    form = CreatePostForm()
    if post.user_id == current_user.id or post.community.is_moderator():
        if get_setting('allow_nsfw', False) is False:
            form.nsfw.render_kw = {'disabled': True}
        if get_setting('allow_nsfl', False) is False:
            form.nsfl.render_kw = {'disabled': True}
        images_disabled = 'disabled' if not get_setting('allow_local_image_posts', True) else ''

        form.communities.choices = [(c.id, c.display_name()) for c in current_user.communities()]

        if form.validate_on_submit():
            save_post(form, post)
            post.community.last_active = datetime.utcnow()
            post.edited_at = datetime.utcnow()
            db.session.commit()
            flash(_('Your changes have been saved.'), 'success')
            return redirect(url_for('post.show_post', post_id=post.id))
        else:
            if post.type == constants.POST_TYPE_ARTICLE:
                form.type.data = 'discussion'
                form.discussion_title.data = post.title
                form.discussion_body.data = post.body
            elif post.type == constants.POST_TYPE_LINK:
                form.type.data = 'link'
                form.link_title.data = post.title
                form.link_url.data = post.url
            elif post.type == constants.POST_TYPE_IMAGE:
                form.type.data = 'image'
                form.image_title.data = post.title
            form.notify_author.data = post.notify_author
            return render_template('post/post_edit.html', title=_('Edit post'), form=form, post=post, images_disabled=images_disabled)
    else:
        abort(401)


@login_required
@bp.route('/post/<int:post_id>/delete', methods=['GET', 'POST'])
def post_delete(post_id: int):
    post = Post.query.get_or_404(post_id)
    community = post.community
    if post.user_id == current_user.id or community.is_moderator():
        post.delete_dependencies()
        db.session.delete(post)
        db.session.commit()
        flash('Post deleted.')
    return redirect(url_for('activitypub.community_profile', actor=community.ap_id if community.ap_id is not None else community.name))


@login_required
@bp.route('/post/<int:post_id>/report', methods=['GET', 'POST'])
def post_report(post_id: int):
    ...

