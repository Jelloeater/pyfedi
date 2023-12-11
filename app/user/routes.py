from datetime import datetime, timedelta

from flask import redirect, url_for, flash, request, make_response, session, Markup, current_app, abort
from flask_login import login_user, logout_user, current_user, login_required
from flask_babel import _

from app import db, cache
from app.models import Post, Community, CommunityMember, User, PostReply, PostVote, Notification, utcnow
from app.user import bp
from app.user.forms import ProfileForm, SettingsForm
from app.utils import get_setting, render_template, markdown_to_html, user_access, markdown_to_text, shorten_string
from sqlalchemy import desc, or_, text


def show_profile(user):
    if user.deleted or user.banned and current_user.is_anonymous():
        abort(404)
    posts = Post.query.filter_by(user_id=user.id).order_by(desc(Post.posted_at)).limit(20).all()
    moderates = Community.query.filter_by(banned=False).join(CommunityMember).filter(CommunityMember.user_id == user.id)\
        .filter(or_(CommunityMember.is_moderator, CommunityMember.is_owner))
    upvoted = Post.query.join(PostVote).filter(Post.id == PostVote.post_id, PostVote.effect > 0).order_by(desc(Post.posted_at)).limit(10).all()
    subscribed = Community.query.filter_by(banned=False).join(CommunityMember).filter(CommunityMember.user_id == user.id).all()
    if current_user.is_anonymous or user.id != current_user.id:
        moderates = moderates.filter(Community.private_mods == False)
    post_replies = PostReply.query.filter_by(user_id=user.id).order_by(desc(PostReply.posted_at)).limit(20).all()
    canonical = user.ap_public_url if user.ap_public_url else None
    user.about_html = markdown_to_html(user.about)
    description = shorten_string(markdown_to_text(user.about), 150) if user.about else None
    return render_template('user/show_profile.html', user=user, posts=posts, post_replies=post_replies,
                           moderates=moderates.all(), canonical=canonical, title=_('Posts by %(user_name)s',
                                                                                   user_name=user.user_name),
                           description=description, subscribed=subscribed, upvoted=upvoted)


@bp.route('/u/<actor>/profile', methods=['GET', 'POST'])
@login_required
def edit_profile(actor):
    actor = actor.strip()
    user = User.query.filter_by(user_name=actor, deleted=False, banned=False, ap_id=None).first()
    if user is None:
        abort(404)
    if current_user.id != user.id:
        abort(401)
    form = ProfileForm()
    if form.validate_on_submit():
        current_user.email = form.email.data
        if form.password_field.data.strip() != '':
            current_user.set_password(form.password_field.data)
        current_user.about = form.about.data
        current_user.flush_cache()
        db.session.commit()

        flash(_('Your changes have been saved.'), 'success')

        return redirect(url_for('user.edit_profile', actor=actor))
    elif request.method == 'GET':
        form.email.data = current_user.email
        form.about.data = current_user.about
        form.password_field.data = ''

    return render_template('user/edit_profile.html', title=_('Edit profile'), form=form, user=current_user)


@bp.route('/u/<actor>/settings', methods=['GET', 'POST'])
@login_required
def change_settings(actor):
    actor = actor.strip()
    user = User.query.filter_by(user_name=actor, deleted=False, banned=False, ap_id=None).first()
    if user is None:
        abort(404)
    if current_user.id != user.id:
        abort(401)
    form = SettingsForm()
    if form.validate_on_submit():
        current_user.newsletter = form.newsletter.data
        current_user.bot = form.bot.data
        current_user.ignore_bots = form.ignore_bots.data
        current_user.show_nsfw = form.nsfw.data
        current_user.show_nsfl = form.nsfl.data
        current_user.searchable = form.searchable.data
        current_user.indexable = form.indexable.data
        current_user.ap_manually_approves_followers = form.manually_approves_followers.data
        db.session.commit()

        flash(_('Your changes have been saved.'), 'success')
        return redirect(url_for('user.change_settings', actor=actor))
    elif request.method == 'GET':
        form.newsletter.data = current_user.newsletter
        form.bot.data = current_user.bot
        form.ignore_bots.data = current_user.ignore_bots
        form.nsfw.data = current_user.show_nsfw
        form.nsfl.data = current_user.show_nsfl
        form.searchable.data = current_user.searchable
        form.indexable.data = current_user.indexable
        form.manually_approves_followers.data = current_user.ap_manually_approves_followers

    return render_template('user/edit_settings.html', title=_('Edit profile'), form=form, user=current_user)


@bp.route('/u/<actor>/ban', methods=['GET'])
@login_required
def ban_profile(actor):
    if user_access('ban users', current_user.id):
        actor = actor.strip()
        user = User.query.filter_by(user_name=actor, deleted=False).first()
        if user is None:
            user = User.query.filter_by(ap_id=actor, deleted=False).first()
            if user is None:
                abort(404)

        if user.id == current_user.id:
            flash(_('You cannot ban yourself.'), 'error')
        else:
            user.banned = True
            db.session.commit()

            flash(f'{actor} has been banned.')
    else:
        abort(401)

    goto = request.args.get('redirect') if 'redirect' in request.args else f'/u/{actor}'
    return redirect(goto)


@bp.route('/u/<actor>/unban', methods=['GET'])
@login_required
def unban_profile(actor):
    if user_access('ban users', current_user.id):
        actor = actor.strip()
        user = User.query.filter_by(user_name=actor, deleted=False).first()
        if user is None:
            user = User.query.filter_by(ap_id=actor, deleted=False).first()
            if user is None:
                abort(404)

        if user.id == current_user.id:
            flash(_('You cannot unban yourself.'), 'error')
        else:
            user.banned = False
            db.session.commit()

            flash(f'{actor} has been unbanned.')
    else:
        abort(401)

    goto = request.args.get('redirect') if 'redirect' in request.args else f'/u/{actor}'
    return redirect(goto)


@bp.route('/u/<actor>/delete', methods=['GET'])
@login_required
def delete_profile(actor):
    if user_access('manage users', current_user.id):
        actor = actor.strip()
        user = User.query.filter_by(user_name=actor, deleted=False).first()
        if user is None:
            user = User.query.filter_by(ap_id=actor, deleted=False).first()
            if user is None:
                abort(404)
        if user.id == current_user.id:
            flash(_('You cannot delete yourself.'), 'error')
        else:
            user.banned = True
            user.deleted = True
            db.session.commit()

            flash(f'{actor} has been deleted.')
    else:
        abort(401)

    goto = request.args.get('redirect') if 'redirect' in request.args else f'/u/{actor}'
    return redirect(goto)


@bp.route('/u/<actor>/ban_purge', methods=['GET'])
@login_required
def ban_purge_profile(actor):
    if user_access('manage users', current_user.id):
        actor = actor.strip()
        user = User.query.filter_by(user_name=actor, deleted=False).first()
        if user is None:
            user = User.query.filter_by(ap_id=actor, deleted=False).first()
            if user is None:
                abort(404)

        if user.id == current_user.id:
            flash(_('You cannot purge yourself.'), 'error')
        else:
            user.banned = True
            user.deleted = True
            db.session.commit()

            user.purge_content()
            db.session.delete(user)
            db.session.commit()

            # todo: empty relevant caches
            # todo: federate deletion

            flash(f'{actor} has been banned, deleted and all their content deleted.')
    else:
        abort(401)

    goto = request.args.get('redirect') if 'redirect' in request.args else f'/u/{actor}'
    return redirect(goto)


@bp.route('/notifications', methods=['GET', 'POST'])
@login_required
def notifications():
    """Remove notifications older than 30 days"""
    db.session.query(Notification).filter(
        Notification.created_at < utcnow() - timedelta(days=30)).delete()
    db.session.commit()

    # Update unread notifications count
    current_user.unread_notifications = Notification.query.filter_by(user_id=current_user.id, read=False).count()
    db.session.commit()

    notification_list = Notification.query.filter_by(user_id=current_user.id).order_by(desc(Notification.created_at)).all()

    return render_template('user/notifications.html', title=_('Notifications'), notifications=notification_list, user=current_user)


@bp.route('/notification/<int:notification_id>/goto', methods=['GET', 'POST'])
@login_required
def notification_goto(notification_id):
    notification = Notification.query.get_or_404(notification_id)
    if notification.user_id == current_user.id:
        if not notification.read:
            current_user.unread_notifications -= 1
        notification.read = True
        db.session.commit()
        return redirect(notification.url)
    else:
        abort(403)


@bp.route('/notification/<int:notification_id>/delete', methods=['GET', 'POST'])
@login_required
def notification_delete(notification_id):
    notification = Notification.query.get_or_404(notification_id)
    if notification.user_id == current_user.id:
        if not notification.read:
            current_user.unread_notifications -= 1
        db.session.delete(notification)
        db.session.commit()
    return redirect(url_for('user.notifications'))


@bp.route('/notifications/all_read', methods=['GET', 'POST'])
@login_required
def notifications_all_read():
    db.session.execute(text('UPDATE notification SET read=true WHERE user_id = :user_id'), {'user_id': current_user.id})
    current_user.unread_notifications = 0
    db.session.commit()
    flash(_('All notifications marked as read.'))
    return redirect(url_for('user.notifications'))
