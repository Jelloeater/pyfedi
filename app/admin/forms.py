from flask_wtf import FlaskForm
from flask_wtf.file import FileRequired, FileAllowed
from wtforms import StringField, PasswordField, SubmitField, HiddenField, BooleanField, TextAreaField, SelectField, \
    FileField, IntegerField
from wtforms.validators import ValidationError, DataRequired, Email, EqualTo, Length, Optional
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
    enable_nsfw = BooleanField(_l('Allow NSFW communities'))
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


class EditCommunityForm(FlaskForm):
    title = StringField(_l('Title'), validators=[DataRequired()])
    url = StringField(_l('Url'), validators=[DataRequired()])
    description = TextAreaField(_l('Description'))
    icon_file = FileField(_('Icon image'))
    banner_file = FileField(_('Banner image'))
    rules = TextAreaField(_l('Rules'))
    nsfw = BooleanField('Porn community')
    local_only = BooleanField('Only accept posts from current instance')
    restricted_to_mods = BooleanField('Only moderators can post')
    new_mods_wanted = BooleanField('New moderators wanted')
    show_home = BooleanField('Posts show on home page')
    show_popular = BooleanField('Posts can be popular')
    show_all = BooleanField('Posts show in All list')
    low_quality = BooleanField("Low quality / toxic - upvotes in here don't add to reputation")
    options = [(-1, _l('Forever')),
               (7, _l('1 week')),
               (14, _l('2 weeks')),
               (28, _l('1 month')),
               (56, _l('2 months')),
               (84, _l('3 months')),
               (168, _l('6 months')),
               (365, _l('1 year')),
               (730, _l('2 years')),
               (1825, _l('5 years')),
               (3650, _l('10 years')),
             ]
    content_retention = SelectField(_l('Retain content'), choices=options, default=1, coerce=int)
    topic = SelectField(_l('Topic'), coerce=int, validators=[Optional()])
    submit = SubmitField(_l('Save'))

    def validate(self, extra_validators=None):
        if not super().validate():
            return False
        if self.url.data.strip() == '':
            self.url.errors.append(_('Url is required.'))
            return False
        else:
            if '-' in self.url.data.strip():
                self.url.errors.append(_('- cannot be in Url. Use _ instead?'))
                return False
        return True


class EditTopicForm(FlaskForm):
    name = StringField(_l('Name'), validators=[DataRequired()])
    submit = SubmitField(_l('Save'))


class EditUserForm(FlaskForm):
    about = TextAreaField(_l('Bio'), validators=[Optional(), Length(min=3, max=5000)])
    matrix_user_id = StringField(_l('Matrix User ID'), validators=[Optional(), Length(max=255)])
    profile_file = FileField(_('Avatar image'))
    banner_file = FileField(_('Top banner image'))
    bot = BooleanField(_l('This profile is a bot'))
    newsletter = BooleanField(_l('Subscribe to email newsletter'))
    ignore_bots = BooleanField(_l('Hide posts by bots'))
    nsfw = BooleanField(_l('Show NSFW posts'))
    nsfl = BooleanField(_l('Show NSFL posts'))
    searchable = BooleanField(_l('Show profile in user list'))
    indexable = BooleanField(_l('Allow search engines to index this profile'))
    manually_approves_followers = BooleanField(_l('Manually approve followers'))
    submit = SubmitField(_l('Save'))
