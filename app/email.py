from flask import current_app, render_template, escape
from app import db, celery
from flask_babel import _, lazy_gettext as _l  # todo: set the locale based on account_id so that _() works
import boto3
from botocore.exceptions import ClientError
from typing import List

AWS_REGION = "ap-southeast-2"
CHARSET = "UTF-8"


def send_password_reset_email(user):
    token = user.get_reset_password_token()
    send_email(_('[PieFed] Reset Your Password'),
               sender=f'PieFed <noreply@{current_app.config["SERVER_NAME"]}>',
               recipients=[user.email],
               text_body=render_template('email/reset_password.txt',
                                         user=user, token=token),
               html_body=render_template('email/reset_password.html',
                                         user=user, token=token))


def send_verification_email(user):
    send_email(_('[PieFed] Please verify your email address'),
               sender=f'PieFed <noreply@{current_app.config["SERVER_NAME"]}>',
               recipients=[user.email],
               text_body=render_template('email/verification.txt', user=user),
               html_body=render_template('email/verification.html', user=user))


def send_welcome_email(user, application_required):
    subject = _('Your application has been approved - welcome to PieFed') if application_required else _('Welcome to PieFed')
    send_email(subject,
               sender=f'PieFed <noreply@{current_app.config["SERVER_NAME"]}>',
               recipients=[user.email],
               text_body=render_template('email/welcome.txt', user=user, application_required=application_required),
               html_body=render_template('email/welcome.html', user=user, application_required=application_required))


@celery.task
def send_async_email(subject, sender, recipients, text_body, html_body, reply_to):
    if 'ngrok.app' in sender:   # for local development
        sender = 'PieFed <noreply@piefed.social>'
        return_path = 'bounces@piefed.social'
    else:
        return_path = 'bounces@' + current_app.config['SERVER_NAME']
    # NB email will not be sent if you have not verified your domain name as an 'Identity' inside AWS SES
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
                    ReturnPath=return_path)
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
                    ReturnPath=return_path,
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
