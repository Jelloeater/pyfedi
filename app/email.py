from flask import current_app, render_template, escape
from app import db, celery
from flask_babel import _, lazy_gettext as _l           # todo: set the locale based on account_id so that _() works
import boto3
from botocore.exceptions import ClientError
from typing import List

AWS_REGION = "ap-southeast-2"
CHARSET = "UTF-8"


@celery.task
def send_async_email(subject, sender, recipients, text_body, html_body, reply_to):
    if type(recipients) == str:
        recipients = [recipients]
    with current_app.app_context():
        try:
            # Create a new SES resource and specify a region.
            amazon_client = boto3.client('ses', region_name=AWS_REGION)
            # Provide the contents of the email.
            if reply_to is None:
                response = amazon_client.send_email(
                    Destination={'ToAddresses': recipients},
                    Message={
                        'Body': {
                            'Html': {
                                'Charset': CHARSET, 'Data': html_body,
                            },
                            'Text': {
                                'Charset': CHARSET, 'Data': text_body,
                            },
                        },
                        'Subject': {
                            'Charset': CHARSET, 'Data': subject,
                        },
                    },
                    Source=sender,
                    ReturnPath='bounces@chorebuster.net')
            else:
                response = amazon_client.send_email(
                    Destination={'ToAddresses': recipients},
                    Message={
                        'Body': {
                            'Html': {
                                'Charset': CHARSET, 'Data': html_body,
                            },
                            'Text': {
                                'Charset': CHARSET, 'Data': text_body,
                            },
                        },
                        'Subject': {
                            'Charset': CHARSET, 'Data': subject,
                        },
                    },
                    Source=sender,
                    ReturnPath='bounces@chorebuster.net',
                    ReplyToAddresses=[reply_to])
                # message.attach_alternative("...AMPHTML content...", "text/x-amp-html")

        except ClientError as e:
            current_app.logger.error('Failed to send email. ' + e.response['Error']['Message'])
            return e.response['Error']['Message']


def send_email(subject, sender, recipients: List[str], text_body, html_body, reply_to=None):
    if current_app.debug:
        send_async_email(subject, sender, recipients, text_body, html_body, reply_to)
    else:
        send_async_email.delay(subject, sender, recipients, text_body, html_body, reply_to)
