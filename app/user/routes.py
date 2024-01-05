from datetime import datetime, timedelta
from time import sleep

from flask import redirect, url_for, flash, request, make_response, session, Markup, current_app, abort
from flask_login import login_user, logout_user, current_user, login_required
from flask_babel import _

from app import db, cache, celery
from app.activitypub.signature import post_request
from app.activitypub.util import default_context
from app.community.util import save_icon_file, save_banner_file
from app.models import Post, Community, CommunityMember, User, PostReply, PostVote, Notification, utcnow, File, Site, \
    Instance, Report, UserBlock
from app.user import bp
from app.user.forms import ProfileForm, SettingsForm, DeleteAccountForm, ReportUserForm
from app.utils import get_setting, render_template, markdown_to_html, user_access, markdown_to_text, shorten_string, \
    is_image_url
from sqlalchemy import desc, or_, text


@bp.route('/people', methods=['GET', 'POST'])
@login_required
def show_people():
    people = User.query.filter_by(ap_id=None, deleted=False, banned=False).all()
    return render_template('user/people.html', people=people)


def show_profile(user):
    if user.deleted or user.banned and current_user.is_anonymous():
        abort(404)

    post_page = request.args.get('post_page', 1, type=int)
    replies_page = request.args.get('replies_page', 1, type=int)

    posts = Post.query.filter_by(user_id=user.id).order_by(desc(Post.posted_at)).paginate(page=post_page, per_page=50, error_out=False)
    moderates = Community.query.filter_by(banned=False).join(CommunityMember).filter(CommunityMember.user_id == user.id)\
        .filter(or_(CommunityMember.is_moderator, CommunityMember.is_owner))
    upvoted = Post.query.join(PostVote).filter(Post.id == PostVote.post_id, PostVote.effect > 0).order_by(desc(Post.posted_at)).limit(10).all()
    subscribed = Community.query.filter_by(banned=False).join(CommunityMember).filter(CommunityMember.user_id == user.id).all()
    if current_user.is_anonymous or user.id != current_user.id:
        moderates = moderates.filter(Community.private_mods == False)
    post_replies = PostReply.query.filter_by(user_id=user.id).order_by(desc(PostReply.posted_at)).paginate(page=replies_page, per_page=50, error_out=False)

    # profile info
    canonical = user.ap_public_url if user.ap_public_url else None
    user.about_html = markdown_to_html(user.about)
    description = shorten_string(markdown_to_text(user.about), 150) if user.about else None

    # pagination urls
    post_next_url = url_for('activitypub.user_profile', actor=user.ap_id if user.ap_id is not None else user.user_name,
                       post_page=posts.next_num) if posts.has_next else None
    post_prev_url = url_for('activitypub.user_profile', actor=user.ap_id if user.ap_id is not None else user.user_name,
                       post_page=posts.prev_num) if posts.has_prev and post_page != 1 else None
    replies_next_url = url_for('activitypub.user_profile', actor=user.ap_id if user.ap_id is not None else user.user_name,
                       replies_page=post_replies.next_num) if post_replies.has_next else None
    replies_prev_url = url_for('activitypub.user_profile', actor=user.ap_id if user.ap_id is not None else user.user_name,
                       replies_page=post_replies.prev_num) if post_replies.has_prev and replies_page != 1 else None

    return render_template('user/show_profile.html', user=user, posts=posts, post_replies=post_replies,
                           moderates=moderates.all(), canonical=canonical, title=_('Posts by %(user_name)s',
                                                                                   user_name=user.user_name),
                           description=description, subscribed=subscribed, upvoted=upvoted,
                           post_next_url=post_next_url, post_prev_url=post_prev_url,
                           replies_next_url=replies_next_url, replies_prev_url=replies_prev_url)


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
    if form.validate_on_submit() and not current_user.banned:
        current_user.title = form.title.data
        current_user.email = form.email.data
        if form.password_field.data.strip() != '':
            current_user.set_password(form.password_field.data)
        current_user.about = form.about.data
        current_user.about_html = markdown_to_html(form.about.data)
        current_user.matrix_user_id = form.matrix_user_id.data
        current_user.bot = form.bot.data
        profile_file = request.files['profile_file']
        if profile_file and profile_file.filename != '':
            # remove old avatar
            if current_user.avatar_id:
                file = File.query.get(current_user.avatar_id)
                file.delete_from_disk()
                current_user.avatar_id = None
                db.session.delete(file)

            # add new avatar
            file = save_icon_file(profile_file, 'users')
            if file:
                current_user.avatar = file
        banner_file = request.files['banner_file']
        if banner_file and banner_file.filename != '':
            # remove old cover
            if current_user.cover_id:
                file = File.query.get(current_user.cover_id)
                file.delete_from_disk()
                current_user.cover_id = None
                db.session.delete(file)

            # add new cover
            file = save_banner_file(banner_file, 'users')
            if file:
                current_user.cover = file
        current_user.flush_cache()
        db.session.commit()

        flash(_('Your changes have been saved.'), 'success')

        return redirect(url_for('user.edit_profile', actor=actor))
    elif request.method == 'GET':
        form.title.data = current_user.title
        form.email.data = current_user.email
        form.about.data = current_user.about
        form.matrix_user_id.data = current_user.matrix_user_id
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


@bp.route('/u/<actor>/block', methods=['GET'])
@login_required
def block_profile(actor):
    actor = actor.strip()
    user = User.query.filter_by(user_name=actor, deleted=False).first()
    if user is None:
        user = User.query.filter_by(ap_id=actor, deleted=False).first()
        if user is None:
            abort(404)

    if user.id == current_user.id:
        flash(_('You cannot block yourself.'), 'error')
    else:
        existing_block = UserBlock.query.filter_by(blocker_id=current_user.id, blocked_id=user.id).first()
        if not existing_block:
            block = UserBlock(blocker_id=current_user.id, blocked_id=user.id)
            db.session.add(block)
            db.session.commit()

        if not user.is_local():
            ...
            # federate block

        flash(f'{actor} has been blocked.')

    goto = request.args.get('redirect') if 'redirect' in request.args else f'/u/{actor}'
    return redirect(goto)


@bp.route('/u/<actor>/unblock', methods=['GET'])
@login_required
def unblock_profile(actor):
    actor = actor.strip()
    user = User.query.filter_by(user_name=actor, deleted=False).first()
    if user is None:
        user = User.query.filter_by(ap_id=actor, deleted=False).first()
        if user is None:
            abort(404)

    if user.id == current_user.id:
        flash(_('You cannot unblock yourself.'), 'error')
    else:
        existing_block = UserBlock.query.filter_by(blocker_id=current_user.id, blocked_id=user.id).first()
        if existing_block:
            db.session.delete(existing_block)
            db.session.commit()

        if not user.is_local():
            ...
            # federate unblock

        flash(f'{actor} has been unblocked.')

    goto = request.args.get('redirect') if 'redirect' in request.args else f'/u/{actor}'
    return redirect(goto)


@bp.route('/u/<actor>/report', methods=['GET', 'POST'])
@login_required
def report_profile(actor):
    if '@' in actor:
        user: User = User.query.filter_by(ap_id=actor, deleted=False, banned=False).first()
    else:
        user: User = User.query.filter_by(user_name=actor, deleted=False, ap_id=None).first()
    form = ReportUserForm()
    if user and not user.banned:
        if form.validate_on_submit():
            report = Report(reasons=form.reasons_to_string(form.reasons.data), description=form.description.data,
                            type=0, reporter_id=current_user.id, suspect_user_id=user.id)
            db.session.add(report)

            # Notify site admin
            already_notified = set()
            for admin in Site.admins():
                if admin.id not in already_notified:
                    notify = Notification(title='Reported user', url=user.ap_id, user_id=admin.id, author_id=current_user.id)
                    db.session.add(notify)
                    admin.unread_notifications += 1
            user.reports += 1
            db.session.commit()

            # todo: federate report to originating instance
            if not user.is_local() and form.report_remote.data:
                ...

            flash(_('%(user_name)s has been reported, thank you!', user_name=actor))
            goto = request.args.get('redirect') if 'redirect' in request.args else f'/u/{actor}'
            return redirect(goto)
        elif request.method == 'GET':
            form.report_remote.data = True

    return render_template('user/user_report.html', title=_('Report user'), form=form, user=user)


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
            user.delete_dependencies()
            db.session.commit()

            flash(f'{actor} has been deleted.')
    else:
        abort(401)

    goto = request.args.get('redirect') if 'redirect' in request.args else f'/u/{actor}'
    return redirect(goto)


@bp.route('/delete_account', methods=['GET', 'POST'])
@login_required
def delete_account():
    form = DeleteAccountForm()
    if form.validate_on_submit():
        files = File.query.join(Post).filter(Post.user_id == current_user.id).all()
        for file in files:
            file.delete_from_disk()
            file.source_url = ''
        if current_user.avatar_id:
            current_user.avatar.delete_from_disk()
            current_user.avatar.source_url = ''
        if current_user.cover_id:
            current_user.cover.delete_from_disk()
            current_user.cover.source_url = ''

        # to verify the deletes, remote servers will GET /u/<actor> so we can't fully delete the account until the POSTs are done
        current_user.banned = True

        db.session.commit()

        if current_app.debug:
            send_deletion_requests(current_user.id)
        else:
            send_deletion_requests.delay(current_user.id)

        logout_user()
        flash(_('Account deletion in progress. Give it a few minutes.'), 'success')
        return redirect(url_for('main.index'))
    elif request.method == 'GET':
        ...

    return render_template('user/delete_account.html', title=_('Delete my account'), form=form, user=current_user)


@celery.task
def send_deletion_requests(user_id):
    user = User.query.get(user_id)
    if user:
        instances = Instance.query.all()
        payload = {
            "@context": default_context(),
            "actor": user.profile_id(),
            "id": f"{user.profile_id()}#delete",
            "object": user.profile_id(),
            "to": [
                "https://www.w3.org/ns/activitystreams#Public"
            ],
            "type": "Delete"
        }
        for instance in instances:
            if instance.inbox and instance.online() and instance.id != 1: # instance id 1 is always the current instance
                post_request(instance.inbox, payload, user.private_key, f"{user.profile_id()}#main-key")

        sleep(5)

        user.banned = True
        user.deleted = True

        db.session.commit()


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
    """Remove notifications older than 90 days"""
    db.session.query(Notification).filter(
        Notification.created_at < utcnow() - timedelta(days=90)).delete()
    db.session.commit()

    # Update unread notifications count, just to be sure
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
