from flask_wtf import FlaskForm, RecaptchaField
from wtforms import StringField, PasswordField, SubmitField, HiddenField
from wtforms.validators import ValidationError, DataRequired, Email, EqualTo, Length
from flask_babel import _, lazy_gettext as _l
from app.models import User, Community


class LoginForm(FlaskForm):
    user_name = StringField(_l('User name'), validators=[DataRequired()])
    password = PasswordField(_l('Password'), validators=[DataRequired()])
    submit = SubmitField(_l('Log In'))


class RegistrationForm(FlaskForm):
    user_name = StringField(_l('User name'), validators=[DataRequired()])
    email = HiddenField(_l('Email'))
    real_email = StringField(_l('Email'), validators=[DataRequired(), Email(), Length(min=5, max=255)])
    password = PasswordField(_l('Password'), validators=[DataRequired(), Length(min=5, max=50)])
    password2 = PasswordField(
        _l('Repeat password'), validators=[DataRequired(),
                                           EqualTo('password')])
    recaptcha = RecaptchaField()

    submit = SubmitField(_l('Register'))

    def validate_real_email(self, email):
        user = User.query.filter_by(email=email.data).first()
        if user is not None:
            raise ValidationError(_('An account with this email address already exists.'))

    def validate_user_name(self, user_name):
        user = User.query.filter_by(user_name=user_name.data).first()
        if user is not None:
            if user.deleted:
                raise ValidationError(_('This username was used in the past and cannot be reused.'))
            else:
                raise ValidationError(_('An account with this user name already exists.'))
        community = Community.query.filter_by(name=user_name.data).first()
        if community is not None:
            raise ValidationError(_('A community with this name exists so it cannot be used for a user.'))


class ResetPasswordRequestForm(FlaskForm):
    email = StringField(_l('Email'), validators=[DataRequired(), Email()])
    submit = SubmitField(_l('Request password reset'))


class ResetPasswordForm(FlaskForm):
    password = PasswordField(_l('Password'), validators=[DataRequired()])
    password2 = PasswordField(
        _l('Repeat password'), validators=[DataRequired(),
                                           EqualTo('password')])
    submit = SubmitField(_l('Set password'))
