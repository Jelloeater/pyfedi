from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField, TextAreaField, BooleanField
from wtforms.validators import ValidationError, DataRequired, Email, EqualTo, Length
from flask_babel import _, lazy_gettext as _l


class AddLocalCommunity(FlaskForm):
    community_name = StringField(_l('Name'), validators=[DataRequired()])
    url = StringField(_l('Url'), render_kw={'placeholder': '/c/'})
    description = TextAreaField(_l('Description'))
    rules = TextAreaField(_l('Rules'))
    nsfw = BooleanField('18+ NSFW')
    submit = SubmitField(_l('Create'))


class SearchRemoteCommunity(FlaskForm):
    address = StringField(_l('Server address'), validators=[DataRequired()])
    submit = SubmitField(_l('Search'))