from flask_wtf import FlaskForm
from wtforms import TextAreaField, SubmitField
from wtforms.validators import DataRequired, Length
from flask_babel import _, lazy_gettext as _l


class NewReplyForm(FlaskForm):
    body = TextAreaField(_l('Body'), render_kw={'placeholder': 'What are your thoughts?', 'rows': 3}, validators={DataRequired(), Length(min=3, max=5000)})
    submit = SubmitField(_l('Comment'))