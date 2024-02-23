from flask import session
from flask_login import current_user
from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField, PasswordField, BooleanField, EmailField, TextAreaField, FileField, \
    RadioField, DateField, SelectField
from wtforms.validators import ValidationError, DataRequired, Email, EqualTo, Length, Optional
from flask_babel import _, lazy_gettext as _l

from app.utils import MultiCheckboxField


class ProfileForm(FlaskForm):
    title = StringField(_l('Display name'), validators=[Optional(), Length(max=255)])
    email = EmailField(_l('Email address'), validators=[Email(), DataRequired(), Length(min=5, max=255)])
    password_field = PasswordField(_l('Set new password'), validators=[Optional(), Length(min=1, max=50)],
                                   render_kw={"autocomplete": 'new-password'})
    about = TextAreaField(_l('Bio'), validators=[Optional(), Length(min=3, max=5000)])
    matrixuserid = StringField(_l('Matrix User ID'), validators=[Optional(), Length(max=255)], render_kw={'autocomplete': 'off'})
    profile_file = FileField(_('Avatar image'))
    banner_file = FileField(_('Top banner image'))
    bot = BooleanField(_l('This profile is a bot'))
    submit = SubmitField(_l('Save profile'))

    def validate_email(self, field):
        if current_user.another_account_using_email(field.data):
            raise ValidationError(_l('That email address is already in use by another account'))

    def validate_matrix_user_id(self, matrix_user_id):
        if not matrix_user_id.data.strip().startswith('@'):
            raise ValidationError(_('Matrix user ids start with @'))


class SettingsForm(FlaskForm):
    newsletter = BooleanField(_l('Subscribe to email newsletter'))
    email_unread = BooleanField(_l('Receive email about missed notifications'))
    ignore_bots = BooleanField(_l('Hide posts by bots'))
    nsfw = BooleanField(_l('Show NSFW posts'))
    nsfl = BooleanField(_l('Show NSFL posts'))
    searchable = BooleanField(_l('Show profile in user list'))
    indexable = BooleanField(_l('Allow search engines to index this profile'))
    manually_approves_followers = BooleanField(_l('Manually approve followers'))
    import_file = FileField(_('Import community subscriptions and user blocks from Lemmy'))
    sorts = [('hot', _l('Hot')),
                      ('top', _l('Top')),
                      ('new', _l('New')),
                      ('active', _l('Active')),
                      ]
    default_sort = SelectField(_l('By default, sort posts by'), choices=sorts, validators=[DataRequired()], coerce=str)
    theme = SelectField(_l('Theme'), coerce=str)
    submit = SubmitField(_l('Save settings'))


class DeleteAccountForm(FlaskForm):
    submit = SubmitField(_l('Yes, delete my account'))


class ReportUserForm(FlaskForm):
    reason_choices = [('1', _l('Breaks community rules')),
                      ('7', _l('Spam')),
                      ('2', _l('Harassment')),
                      ('3', _l('Threatening violence')),
                      ('4', _l('Promoting hate / genocide')),
                      ('15', _l('Misinformation / disinformation')),
                      ('16', _l('Racism, sexism, transphobia')),
                      ('17', _l('Malicious reporting')),
                      ('6', _l('Sharing personal info - doxing')),
                      ('5', _l('Minor abuse or sexualization')),
                      ('8', _l('Non-consensual intimate media')),
                      ('9', _l('Prohibited transaction')), ('10', _l('Impersonation')),
                      ('11', _l('Copyright violation')), ('12', _l('Trademark violation')),
                      ('13', _l('Self-harm or suicide')),
                      ('14', _l('Other'))]
    reasons = MultiCheckboxField(_l('Reason'), choices=reason_choices)
    description = StringField(_l('More info'))
    report_remote = BooleanField('Also send report to originating instance')
    submit = SubmitField(_l('Report'))

    def reasons_to_string(self, reason_data) -> str:
        result = []
        for reason_id in reason_data:
            for choice in self.reason_choices:
                if choice[0] == reason_id:
                    result.append(str(choice[1]))
        return ', '.join(result)


class FilterEditForm(FlaskForm):
    title = StringField(_l('Name'), validators={DataRequired(), Length(min=3, max=50)})
    filter_home = BooleanField(_l('Home feed'), default=True)
    filter_posts = BooleanField(_l('Posts in communities'))
    filter_replies = BooleanField(_l('Comments on posts'))
    hide_type_choices = [(0, _l('Make semi-transparent')), (1, _l('Hide completely'))]
    hide_type = RadioField(_l('Action to take'), choices=hide_type_choices, default=1, coerce=int)
    keywords = TextAreaField(_l('Keywords that trigger this filter'),
                         render_kw={'placeholder': 'One keyword or phrase per line', 'rows': 3},
                         validators={DataRequired(), Length(min=3, max=500)})
    expire_after = DateField(_l('Expire after'), validators={Optional()})
    submit = SubmitField(_l('Save'))
