from flask import request, g
from flask_login import current_user
from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField, TextAreaField, BooleanField, HiddenField, SelectField, FileField
from wtforms.validators import ValidationError, DataRequired, Email, EqualTo, Length, Optional
from flask_babel import _, lazy_gettext as _l

from app import db


class AddReply(FlaskForm):
    message = TextAreaField(_l('Message'), validators=[DataRequired(), Length(min=1, max=5000)], render_kw={'placeholder': 'Type a reply here...'})
    recipient_id = HiddenField()
    submit = SubmitField(_l('Reply'))
