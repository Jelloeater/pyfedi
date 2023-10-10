from flask import redirect, url_for, flash, request, make_response, session, Markup, current_app, abort
from flask_login import login_user, logout_user, current_user, login_required
from flask_babel import _

from app import db
from app.models import Post, Community, CommunityMember, User, PostReply
from app.user import bp
from app.user.forms import ProfileForm, SettingsForm
from app.utils import get_setting, render_template, markdown_to_html
from sqlalchemy import desc, or_


def show_profile(user):
    posts = Post.query.filter_by(user_id=user.id).order_by(desc(Post.posted_at)).all()
    moderates = Community.query.filter_by(banned=False).join(CommunityMember).filter(or_(CommunityMember.is_moderator, CommunityMember.is_owner))
    if user.id != current_user.id:
        moderates = moderates.filter(Community.private_mods == False)
    post_replies = PostReply.query.filter_by(user_id=user.id).order_by(desc(PostReply.posted_at)).all()
    canonical = user.ap_public_url if user.ap_public_url else None
    user.about_html = markdown_to_html(user.about)
    return render_template('user/show_profile.html', user=user, posts=posts, post_replies=post_replies,
                           moderates=moderates.all(), canonical=canonical, title=_('Posts by %(user_name)s',
                                                                                   user_name=user.user_name))


@bp.route('/u/<actor>/profile', methods=['GET', 'POST'])
def edit_profile(actor):
    actor = actor.strip()
    user = User.query.filter_by(user_name=actor, deleted=False, banned=False, ap_id=None).first()
    if user is None:
        abort(404)
    form = ProfileForm()
    if form.validate_on_submit():
        current_user.email = form.email.data
        if form.password_field.data.strip() != '':
            current_user.set_password(form.password_field.data)
        current_user.about = form.about.data
        db.session.commit()

        flash(_('Your changes have been saved.'), 'success')
        return redirect(url_for('user.edit_profile', actor=actor))
    elif request.method == 'GET':
        form.email.data = current_user.email
        form.about.data = current_user.about
        form.password_field.data = ''

    return render_template('user/edit_profile.html', title=_('Edit profile'), form=form, user=current_user)


@bp.route('/u/<actor>/settings', methods=['GET', 'POST'])
def change_settings(actor):
    actor = actor.strip()
    user = User.query.filter_by(user_name=actor, deleted=False, banned=False, ap_id=None).first()
    if user is None:
        abort(404)
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
