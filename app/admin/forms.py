from flask_wtf import FlaskForm
from flask_wtf.file import FileRequired, FileAllowed
from wtforms import StringField, PasswordField, SubmitField, HiddenField, BooleanField, TextAreaField, SelectField, \
    FileField, IntegerField
from wtforms.validators import ValidationError, DataRequired, Email, EqualTo, Length
from flask_babel import _, lazy_gettext as _l


class SiteProfileForm(FlaskForm):
    name = StringField(_l('Name'))
    description = StringField(_l('Tagline'))
    icon = FileField(_('Icon'), validators=[
        FileAllowed(['jpg', 'jpeg', 'png', 'webp'], 'Images only!')
    ])
    sidebar = TextAreaField(_l('Sidebar'))
    legal_information = TextAreaField(_l('Legal information'))
    submit = SubmitField(_l('Save'))


class SiteMiscForm(FlaskForm):
    enable_downvotes = BooleanField(_l('Enable downvotes'))
    allow_local_image_posts = BooleanField(_l('Allow local image posts'))
    remote_image_cache_days = IntegerField(_l('Days to cache images from remote instances for'))
    enable_nsfw = BooleanField(_l('Allow NSFW communities and posts'))
    enable_nsfl = BooleanField(_l('Allow NSFL communities and posts'))
    community_creation_admin_only = BooleanField(_l('Only admins can create new local communities'))
    reports_email_admins = BooleanField(_l('Notify admins about reports, not just moderators'))
    types = [('Open', _l('Open')), ('RequireApplication', _l('Require application')), ('Closed', _l('Closed'))]
    registration_mode = SelectField(_l('Registration mode'), choices=types, default=1, coerce=str)
    application_question = TextAreaField(_l('Question to ask people applying for an account'))
    submit = SubmitField(_l('Save'))


class FederationForm(FlaskForm):
    use_allowlist = BooleanField(_l('Allowlist instead of blocklist'))
    allowlist = TextAreaField(_l('Allow federation with these instances'))
    use_blocklist = BooleanField(_l('Blocklist instead of allowlist'))
    blocklist = TextAreaField(_l('Deny federation with these instances'))
    submit = SubmitField(_l('Save'))
