from datetime import date, datetime, timedelta
from flask import render_template, redirect, url_for, flash, request, make_response, session, Markup
from werkzeug.urls import url_parse
from flask_login import login_user, logout_user, current_user
from flask_babel import _
from app import db
from app.auth import bp
from app.auth.forms import LoginForm, RegistrationForm, ResetPasswordRequestForm, ResetPasswordForm
from app.models import User
from app.auth.email import send_password_reset_email, send_welcome_email
from sqlalchemy import text


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
    if form.validate_on_submit():
        if form.email.data == '': # ignore any registration where the email field is filled out. spam prevention
            if form.real_email.data.lower().startswith('postmaster@') or form.real_email.data.lower().startswith('abuse@') or \
                    form.real_email.data.lower().startswith('noc@'):
                flash(_('Sorry, you cannot use that email address'), 'error')
            else:
                user = User(username=form.user_name.data, email=form.real_email.data, last_seen=datetime.utcnow())
                user.set_password(form.password.data)
                db.session.add_all([user])
                db.session.commit()
                login_user(user, remember=True)
                send_welcome_email(user)

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