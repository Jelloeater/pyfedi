from datetime import date, datetime, timedelta
from flask import redirect, url_for, flash, request, make_response, session, Markup, current_app, g
from werkzeug.urls import url_parse
from flask_login import login_user, logout_user, current_user
from flask_babel import _
from app import db, cache
from app.auth import bp
from app.auth.forms import LoginForm, RegistrationForm, ResetPasswordRequestForm, ResetPasswordForm
from app.auth.util import random_token
from app.models import User, utcnow, IpBan
from app.auth.email import send_password_reset_email, send_welcome_email, send_verification_email
from app.activitypub.signature import RsaKeys
from app.utils import render_template, ip_address, user_ip_banned, user_cookie_banned, banned_ip_addresses


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
                if "@gmail.com" in user.email:
                    message = Markup(_('Invalid password. Please click the "Login using Google" button or <a href="/auth/reset_password_request">reset your password</a>.'))
                    flash(message, 'warning')
                else:
                    message = Markup(_('Invalid password. Please <a href="/auth/reset_password_request">reset your password</a>.'))
                    flash(message, 'error')
                return redirect(url_for('auth.login'))
            flash(_('Invalid password'))
            return redirect(url_for('auth.login'))
        if user.banned or user_ip_banned() or user_cookie_banned():
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
        login_user(user, remember=True)
        current_user.last_seen = utcnow()
        current_user.verification_token = ''
        current_user.ip_address = ip_address()
        db.session.commit()
        next_page = request.args.get('next')
        if not next_page or url_parse(next_page).netloc != '':
            next_page = url_for('main.index')
        return redirect(next_page)
    return render_template('auth/login.html', title=_('Login'), form=form)


@bp.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('main.index'))


@bp.route('/register', methods=['GET', 'POST'])
def register():
    disallowed_usernames = ['admin']
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))
    form = RegistrationForm()
    if current_app.config['MODE'] == 'development':
        del form.recaptcha
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
                user = User(user_name=form.user_name.data, title=form.user_name.data, email=form.real_email.data,
                            verification_token=verification_token, instance_id=1, ip_address=ip_address(),
                            banned=user_ip_banned() or user_cookie_banned())
                user.set_password(form.password.data)
                db.session.add(user)
                db.session.commit()
                login_user(user, remember=True)
                send_welcome_email(user)
                send_verification_email(user)

                if current_app.config['MODE'] == 'development':
                    current_app.logger.info('Verify account:' + url_for('auth.verify_email', token=user.verification_token, _external=True))

                flash(_('Great, you are now a registered user! Choose some communities to join. Use the topic filter to narrow things down.'))

        resp = make_response(redirect(url_for('main.list_communities')))
        if user_ip_banned():
            resp.set_cookie('sesion', '17489047567495', expires=datetime(year=2099, month=12, day=30))
        return resp
    return render_template('auth/register.html', title=_('Register'), form=form, site=g.site)


@bp.route('/reset_password_request', methods=['GET', 'POST'])
def reset_password_request():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))
    form = ResetPasswordRequestForm()
    if form.validate_on_submit():
        if form.email.data.lower().startswith('postmaster@') or form.email.data.lower().startswith('abuse@') or \
                form.email.data.lower().startswith('noc@'):
            flash(_('Sorry, you cannot use that email address'), 'error')
        else:
            user = User.query.filter_by(email=form.email.data).first()
            if user:
                send_password_reset_email(user)
                flash(_('Check your email for the instructions to reset your password'))
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
        flash(_('Your password has been reset.'))
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
            user.last_seen = utcnow()
            private_key, public_key = RsaKeys.generate_keypair()
            user.private_key = private_key
            user.public_key = public_key
            user.ap_profile_id = f"https://{current_app.config['SERVER_NAME']}/u/{user.user_name}"
            user.ap_public_url = f"https://{current_app.config['SERVER_NAME']}/u/{user.user_name}"
            user.ap_inbox_url = f"https://{current_app.config['SERVER_NAME']}/u/{user.user_name}/inbox"
            db.session.commit()
            flash(_('Thank you for verifying your email address.'))
        else:
            flash(_('Email address validation failed.'), 'error')
        return redirect(url_for('main.index'))


@bp.route('/validation_required')
def validation_required():
    return render_template('auth/validation_required.html')


@bp.route('/permission_denied')
def permission_denied():
    return render_template('auth/permission_denied.html')
