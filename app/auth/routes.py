from datetime import date, datetime, timedelta
from flask import redirect, url_for, flash, request, make_response, session, Markup, current_app
from werkzeug.urls import url_parse
from flask_login import login_user, logout_user, current_user
from flask_babel import _
from app import db
from app.auth import bp
from app.auth.forms import LoginForm, RegistrationForm, ResetPasswordRequestForm, ResetPasswordForm
from app.auth.util import random_token
from app.models import User
from app.auth.email import send_password_reset_email, send_welcome_email, send_verification_email
from app.activitypub.signature import RsaKeys
from app.utils import render_template


@bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        next_page = request.args.get('next')
        if not next_page or url_parse(next_page).netloc != '':
            next_page = url_for('main.index')
        return redirect(next_page)
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(user_name=form.user_name.data).first()
        if user is None:
            flash(_('No account exists with that user name address'), 'error')
            return redirect(url_for('auth.login'))
        if user.banned:
            flash(_('You have been banned.', 'error'))
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
        login_user(user, remember=True)
        current_user.last_seen = datetime.utcnow()
        current_user.verification_token = ''
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
            else:
                verification_token = random_token(16)
                user = User(user_name=form.user_name.data, email=form.real_email.data,
                            verification_token=verification_token)
                user.set_password(form.password.data)
                db.session.add(user)
                db.session.commit()
                login_user(user, remember=True)
                send_welcome_email(user)
                send_verification_email(user)

                if current_app.config['MODE'] == 'development':
                    current_app.logger.info('Verify account:' + url_for('auth.verify_email', token=user.verification_token, _external=True))

                flash(_('Great, you are now a registered user!'))

        # set a cookie so the login button is emphasised on the public site, for future visits
        resp = make_response(redirect(url_for('main.index')))
        resp.set_cookie('logged_in_before', value='1', expires=datetime.now() + timedelta(weeks=300),
                        domain='.chorebuster.net')
        return resp
    return render_template('auth/register.html', title=_('Register'),
                           form=form)


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
            user.last_seen = datetime.utcnow()
            private_key, public_key = RsaKeys.generate_keypair()
            user.private_key = private_key
            user.public_key = public_key
            db.session.commit()
            flash(_('Thank you for verifying your email address. You can now post content and vote.'))
        else:
            flash(_('Email address validation failed.'), 'error')
        return redirect(url_for('main.index'))


@bp.route('/validation_required')
def validation_required():
    return render_template('auth/validation_required.html')
