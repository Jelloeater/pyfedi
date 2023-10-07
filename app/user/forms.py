from flask import session
from flask_login import current_user
from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField, PasswordField, BooleanField, EmailField, TextAreaField, FileField
from wtforms.validators import ValidationError, DataRequired, Email, EqualTo, Length, Optional
from flask_babel import _, lazy_gettext as _l


class ProfileForm(FlaskForm):
    email = EmailField(_l('Email address'), validators=[Email(), DataRequired(), Length(min=5, max=255)])
    password_field = PasswordField(_l('Set new password'), validators=[Optional(), Length(min=1, max=50)],
                                   render_kw={"autocomplete": 'Off'})
    about = TextAreaField(_l('Bio'), validators=[Optional(), Length(min=3, max=5000)])
    submit = SubmitField(_l('Save profile'))

    def validate_email(self, field):
        if current_user.another_account_using_email(field.data):
            raise ValidationError(_l('That email address is already in use by another account'))


class SettingsForm(FlaskForm):
    newsletter = BooleanField(_l('Subscribe to email newsletter'))
    bot = BooleanField(_l('This profile is a bot'))
    ignore_bots = BooleanField(_l('Hide posts by bots'))
    nsfw = BooleanField(_l('Show NSFW posts'))
    nsfl = BooleanField(_l('Show NSFL posts'))
    searchable = BooleanField(_l('Show profile in fediverse searches'))
    indexable = BooleanField(_l('Allow search engines to index this profile'))
    manually_approves_followers = BooleanField(_l('Manually approve followers'))
    submit = SubmitField(_l('Save settings'))