from flask_wtf import FlaskForm
from wtforms import TextAreaField, SubmitField, BooleanField, StringField
from wtforms.validators import DataRequired, Length
from flask_babel import _, lazy_gettext as _l

from app.utils import MultiCheckboxField


class NewReplyForm(FlaskForm):
    body = TextAreaField(_l('Body'), render_kw={'placeholder': 'What are your thoughts?', 'rows': 3}, validators={DataRequired(), Length(min=3, max=5000)})
    notify_author = BooleanField(_l('Notify about replies'))
    submit = SubmitField(_l('Comment'))


class ReportPostForm(FlaskForm):
    reason_choices = [('1', _l('Breaks community rules')), ('7', _l('Spam')), ('2', _l('Harassment')),
                      ('3', _l('Threatening violence')), ('4', _l('Hate / genocide')),
                      ('15', _l('Misinformation / disinformation')),
                      ('16', _l('Racism, sexism, transphobia')),
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


class MeaCulpaForm(FlaskForm):
    submit = SubmitField(_l('I changed my mind'))
