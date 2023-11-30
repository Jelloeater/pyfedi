from flask_wtf import FlaskForm
from wtforms import TextAreaField, SubmitField, BooleanField
from wtforms.validators import DataRequired, Length
from flask_babel import _, lazy_gettext as _l


class NewReplyForm(FlaskForm):
    body = TextAreaField(_l('Body'), render_kw={'placeholder': 'What are your thoughts?', 'rows': 3}, validators={DataRequired(), Length(min=3, max=5000)})
    notify_author = BooleanField(_l('Notify about replies'))
    submit = SubmitField(_l('Comment'))