from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField, TextAreaField, BooleanField, HiddenField, SelectField, FileField
from wtforms.validators import ValidationError, DataRequired, Email, EqualTo, Length, Optional
from flask_babel import _, lazy_gettext as _l

from app.utils import domain_from_url, MultiCheckboxField


class AddLocalCommunity(FlaskForm):
    community_name = StringField(_l('Name'), validators=[DataRequired()])
    url = StringField(_l('Url'))
    description = TextAreaField(_l('Description'))
    icon_file = FileField(_('Icon image'))
    banner_file = FileField(_('Banner image'))
    rules = TextAreaField(_l('Rules'))
    nsfw = BooleanField('18+ NSFW')
    submit = SubmitField(_l('Create'))

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


class SearchRemoteCommunity(FlaskForm):
    address = StringField(_l('Community address'), render_kw={'placeholder': 'e.g. !name@server'}, validators=[DataRequired()])
    submit = SubmitField(_l('Search'))


class CreatePostForm(FlaskForm):
    communities = SelectField(_l('Community'), validators=[DataRequired()], coerce=int)
    type = HiddenField() # https://getbootstrap.com/docs/4.6/components/navs/#tabs
    discussion_title = StringField(_l('Title'), validators={Optional(), Length(min=3, max=255)})
    discussion_body = TextAreaField(_l('Body'), render_kw={'placeholder': 'Text (optional)'})
    link_title = StringField(_l('Title'), validators={Optional(), Length(min=3, max=255)})
    link_url = StringField(_l('URL'), render_kw={'placeholder': 'https://...'})
    image_title = StringField(_l('Title'), validators={Optional(), Length(min=3, max=255)})
    image_file = FileField(_('Image'))
    # flair = SelectField(_l('Flair'), coerce=int)
    nsfw = BooleanField(_l('NSFW'))
    nsfl = BooleanField(_l('NSFL'))
    notify_author = BooleanField(_l('Notify about replies'))
    submit = SubmitField(_l('Save'))

    def validate(self, extra_validators=None) -> bool:
        if not super().validate():
            return False
        if self.type.data is None or self.type.data == '':
            self.type.data = 'discussion'

        if self.type.data == 'discussion':
            if self.discussion_title.data == '':
                self.discussion_title.errors.append(_('Title is required.'))
                return False
        elif self.type.data == 'link':
            if self.link_title.data == '':
                self.link_title.errors.append(_('Title is required.'))
                return False
            if self.link_url.data == '':
                self.link_url.errors.append(_('URL is required.'))
                return False
            domain = domain_from_url(self.link_url.data, create=False)
            if domain and domain.banned:
                self.link_url.errors.append(_(f"Links to %s are not allowed.".format(domain.name)))
                return False
        elif self.type.data == 'image':
            if self.image_title.data == '':
                self.image_title.errors.append(_('Title is required.'))
                return False
            if self.image_file.data == '':
                self.image_file.errors.append(_('File is required.'))
                return False
        elif self.type.data == 'poll':
            self.discussion_title.errors.append(_('Poll not implemented yet.'))
            return False

        return True


class ReportCommunityForm(FlaskForm):
    reason_choices = [('1', _l('Breaks instance rules')),
                      ('2', _l('Abandoned by moderators')),
                      ('3', _l('Cult')),
                      ('4', _l('Scam')),
                      ('5', _l('Alt-right pipeline')),
                      ('6', _l('Hate / genocide')),
                      ('7', _l('Other')),
                      ]
    reasons = MultiCheckboxField(_l('Reason'), choices=reason_choices)
    description = StringField(_l('More info'))
    report_remote = BooleanField('Also send report to originating instance')
    submit = SubmitField(_l('Report'))


class DeleteCommunityForm(FlaskForm):
    submit = SubmitField(_l('Delete community'))
