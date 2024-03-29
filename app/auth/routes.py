from datetime import date, datetime, timedelta
from flask import redirect, url_for, flash, request, make_response, session, Markup, current_app, g
from werkzeug.urls import url_parse
from flask_login import login_user, logout_user, current_user
from flask_babel import _
from wtforms import Label

from app import db, cache
from app.auth import bp
from app.auth.forms import LoginForm, RegistrationForm, ResetPasswordRequestForm, ResetPasswordForm
from app.auth.util import random_token, normalize_utf
from app.email import send_verification_email, send_password_reset_email
from app.models import User, utcnow, IpBan, UserRegistration, Notification, Site
from app.utils import render_template, ip_address, user_ip_banned, user_cookie_banned, banned_ip_addresses, \
    finalize_user_setup


@bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        next_page = request.args.get('next')
        if not next_page or url_parse(next_page).netloc != '':
            next_page = url_for('main.index')
        return redirect(next_page)
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(user_name=form.user_name.data, ap_id=None).first()
        if user is None:
            flash(_('No account exists with that user name.'), 'error')
            return redirect(url_for('auth.login'))
        if user.deleted:
            flash(_('No account exists with that user name.'), 'error')
            return redirect(url_for('auth.login'))
        if not user.check_password(form.password.data):
            if user.password_hash is None:
                message = Markup(_('Invalid password. Please <a href="/auth/reset_password_request">reset your password</a>.'))
                flash(message, 'error')
                return redirect(url_for('auth.login'))
            flash(_('Invalid password'))
            return redirect(url_for('auth.login'))
        if user.id != 1 and (user.banned or user_ip_banned() or user_cookie_banned()):
            flash(_('You have been banned.'), 'error')

            response = make_response(redirect(url_for('auth.login')))
            # Detect if a banned user tried to log in from a new IP address
            if user.banned and not user_ip_banned():
                # If so, ban their new IP address as well
                new_ip_ban = IpBan(ip_address=ip_address(), notes=user.user_name + ' used new IP address')
                db.session.add(new_ip_ban)
                db.session.commit()
                cache.delete_memoized(banned_ip_addresses)

            # Set a cookie so we have another way to track banned people
            response.set_cookie('sesion', '17489047567495', expires=datetime(year=2099, month=12, day=30))
            return response
        if user.waiting_for_approval():
            return redirect(url_for('auth.please_wait'))
        login_user(user, remember=True)
        current_user.last_seen = utcnow()
        current_user.ip_address = ip_address()
        db.session.commit()
        next_page = request.args.get('next')
        if not next_page or url_parse(next_page).netloc != '':
            if len(current_user.communities()) == 0:
                next_page = url_for('topic.choose_topics')
            else:
                next_page = url_for('main.index')
        response = make_response(redirect(next_page))
        if form.low_bandwidth_mode.data:
            response.set_cookie('low_bandwidth', '1', expires=datetime(year=2099, month=12, day=30))
        else:
            response.set_cookie('low_bandwidth', '0', expires=datetime(year=2099, month=12, day=30))
        return response
    return render_template('auth/login.html', title=_('Login'), form=form)


@bp.route('/logout')
def logout():
    logout_user()
    response = make_response(redirect(url_for('main.index')))
    response.set_cookie('low_bandwidth', '0', expires=datetime(year=2099, month=12, day=30))
    return response


@bp.route('/register', methods=['GET', 'POST'])
def register():
    disallowed_usernames = ['admin']
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))
    form = RegistrationForm()
    if g.site.registration_mode != 'RequireApplication':
        form.question.validators = ()
    if form.validate_on_submit():
        if form.email.data == '': # ignore any registration where the email field is filled out. spam prevention
            if form.real_email.data.lower().startswith('postmaster@') or form.real_email.data.lower().startswith('abuse@') or \
                    form.real_email.data.lower().startswith('noc@'):
                flash(_('Sorry, you cannot use that email address'), 'error')
            if form.user_name.data in disallowed_usernames:
                flash(_('Sorry, you cannot use that user name'), 'error')
            else:
                verification_token = random_token(16)
                form.user_name.data = form.user_name.data.strip()
                before_normalize = form.user_name.data
                form.user_name.data = normalize_utf(form.user_name.data)
                if before_normalize != form.user_name.data:
                    flash(_('Your username contained special letters so it was changed to %(name)s.', name=form.user_name.data), 'warning')
                user = User(user_name=form.user_name.data, title=form.user_name.data, email=form.real_email.data,
                            verification_token=verification_token, instance_id=1, ip_address=ip_address(),
                            banned=user_ip_banned() or user_cookie_banned(), email_unread_sent=False,
                            referrer=session.get('Referer'))
                user.set_password(form.password.data)
                db.session.add(user)
                db.session.commit()
                send_verification_email(user)
                if current_app.config['MODE'] == 'development':
                    current_app.logger.info('Verify account:' + url_for('auth.verify_email', token=user.verification_token, _external=True))
                if g.site.registration_mode == 'RequireApplication':
                    application = UserRegistration(user_id=user.id, answer=form.question.data)
                    db.session.add(application)
                    for admin in Site.admins():
                        notify = Notification(title='New registration', url='/admin/approve_registrations', user_id=admin.id,
                                          author_id=user.id)
                        admin.unread_notifications += 1
                        db.session.add(notify)
                        # todo: notify everyone with the "approve registrations" permission, instead of just all admins
                    db.session.commit()
                    return redirect(url_for('auth.please_wait'))
                else:
                    return redirect(url_for('auth.check_email'))

        resp = make_response(redirect(url_for('topic.choose_topics')))
        if user_ip_banned():
            resp.set_cookie('sesion', '17489047567495', expires=datetime(year=2099, month=12, day=30))
        return resp
    else:
        if g.site.registration_mode == 'RequireApplication' and g.site.application_question != '':
            form.question.label = Label('question', g.site.application_question)
        if g.site.registration_mode != 'RequireApplication':
            del form.question
        return render_template('auth/register.html', title=_('Register'), form=form, site=g.site)


@bp.route('/please_wait', methods=['GET'])
def please_wait():
    return render_template('auth/please_wait.html', title=_('Account under review'), site=g.site)


@bp.route('/check_email', methods=['GET'])
def check_email():
    return render_template('auth/check_email.html', title=_('Check your email'), site=g.site)


@bp.route('/reset_password_request', methods=['GET', 'POST'])
def reset_password_request():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))
    form = ResetPasswordRequestForm()
    if form.validate_on_submit():
        if form.email.data.lower().startswith('postmaster@') or form.email.data.lower().startswith('abuse@') or \
                form.email.data.lower().startswith('noc@'):
            flash(_('Sorry, you cannot use that email address.'), 'error')
        else:
            user = User.query.filter_by(email=form.email.data).first()
            if user:
                send_password_reset_email(user)
                flash(_('Check your email for a link to reset your password.'))
                return redirect(url_for('auth.login'))
            else:
                flash(_('No account with that email address exists'), 'warning')
    return render_template('auth/reset_password_request.html',
                           title=_('Reset Password'), form=form)


@bp.route('/reset_password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))
    user = User.verify_reset_password_token(token)
    if not user:
        return redirect(url_for('main.index'))
    form = ResetPasswordForm()
    if form.validate_on_submit():
        user.set_password(form.password.data)
        db.session.commit()
        flash(_('Your password has been reset. Please use it to log in with user name of %(name)s.', name=user.user_name))
        return redirect(url_for('auth.login'))
    return render_template('auth/reset_password.html', form=form)


@bp.route('/verify_email/<token>')
def verify_email(token):
    if token != '':
        user = User.query.filter_by(verification_token=token).first()
        if user is not None:
            if user.banned:
                flash('You have been banned.', 'error')
                return redirect(url_for('main.index'))
            if user.verified:   # guard against users double-clicking the link in the email
                return redirect(url_for('main.index'))
            user.verified = True
            db.session.commit()
            if not user.waiting_for_approval():
                finalize_user_setup(user)
            else:
                flash(_('Thank you for verifying your email address.'))
        else:
            flash(_('Email address validation failed.'), 'error')
        if user.waiting_for_approval():
            return redirect(url_for('auth.please_wait'))
        else:
            login_user(user, remember=True)
            if len(user.communities()) == 0:
                return redirect(url_for('topic.choose_topics'))
            else:
                return redirect(url_for('main.index'))


@bp.route('/validation_required')
def validation_required():
    return render_template('auth/validation_required.html')


@bp.route('/permission_denied')
def permission_denied():
    return render_template('auth/permission_denied.html')
