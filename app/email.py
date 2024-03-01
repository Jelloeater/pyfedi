from flask import current_app, render_template, escape
from app import db, celery
from flask_babel import _, lazy_gettext as _l  # todo: set the locale based on account_id so that _() works
import boto3
from botocore.exceptions import ClientError
from typing import List
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

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
        if current_app.config['MAIL_SERVER']:
            email_sender = SMTPEmailService(current_app.config['MAIL_USERNAME'],
                                            current_app.config['MAIL_PASSWORD'],
                                            (current_app.config['MAIL_SERVER'], current_app.config['MAIL_PORT']),
                                            use_tls=current_app.config['MAIL_USE_TLS'])
            email_sender.set_message(text_body, subject, sender, html_body)  # sender = 'John Doe <j.doe@server.com>'
            email_sender.set_recipients(recipients)
            email_sender.connect()
            email_sender.send_all(close_connection=True)
        elif current_app.config['AWS_REGION']:
            try:
                # Create a new SES resource and specify a region.
                amazon_client = boto3.client('ses', region_name=current_app.config['AWS_REGION'])
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


class SMTPEmailService:
    """
    Contains email contents, connection settings and recipient settings. Has functions to compose and send mail. MailSenders are tied to an SMTP server, which must be specified when the instance is created. The default SMTP server is Google's Gmail server, with a connection over TLS.
    :param in_username: Username for mail server login (required)
    :param in_password: Password for mail server login (required)
    :param in_server: SMTP server to connect to
    :param use_tls: Select whether to connect over SSL (False) or TLS (True). Keep in mind that SMTP servers use different ports for SSL and TLS.
    """

    def __init__(self, in_username, in_password, in_server, use_tls):
        self.username = in_username
        self.password = in_password
        self.server_name = in_server[0]
        self.server_port = in_server[1]
        self.use_tls = use_tls

        if not self.use_tls:
            self.smtpserver = smtplib.SMTP_SSL(self.server_name, self.server_port)
        else:
            self.smtpserver = smtplib.SMTP(self.server_name, self.server_port)
        self.connected = False
        self.recipients = []

    def __str__(self):
        return "Type: Mail Sender \n" \
               "Connection to server {}, port {} \n" \
               "Connected: {} \n" \
               "Username: {}, Password: {}".format(
                   self.server_name, self.server_port, self.connected, self.username, self.password)

    def set_message(self, plaintext, subject="", in_from=None, htmltext=None):
        """
        Creates the MIME message to be sent by e-mail. Optionally allows adding subject and 'from' field. Sets up empty recipient fields. To use html messages specify an htmltext input
        :param plaintext: Plaintext email body (required even when HTML message is specified, as fallback)
        :param subject: Subject line (optional)
        :param in_from: Sender address (optional, whether this setting is copied by the SMTP server depends on the server's settings)
        :param htmltext: HTML version of the email body (optional) (If you want to use an HTML message but set it later, pass an empty string here)
        """

        if htmltext is not None:
            self.html_ready = True
        else:
            self.html_ready = False

        if self.html_ready:
            # 'alternative' allows attaching an html version of the message later
            self.msg = MIMEMultipart('alternative')
            self.msg.attach(MIMEText(plaintext, 'plain'))
            self.msg.attach(MIMEText(htmltext, 'html'))
        else:
            self.msg = MIMEText(plaintext, 'plain')

        self.msg['Subject'] = subject
        if in_from is None:
            self.msg['From'] = self.username
        else:
            self.msg['From'] = in_from
        self.msg["To"] = None
        self.msg["CC"] = None
        self.msg["BCC"] = None

    def clear_message(self):
        """
        Remove the whole email body. If both plaintext and html are attached both are removed
        """
        self.msg.set_payload("")

    def set_subject(self, in_subject):
        self.msg.replace_header("Subject", in_subject)

    def set_from(self, in_from):
        self.msg.replace_header("From", in_from)

    def set_plaintext(self, in_body_text):
        """
        Set plaintext message: replaces entire payload if no html is used, otherwise replaces the plaintext only
        :param in_body_text: Plaintext email body, replaces old plaintext email body
        """
        if not self.html_ready:
            self.msg.set_payload(in_body_text)
        else:
            payload = self.msg.get_payload()
            payload[0] = MIMEText(in_body_text)
            self.msg.set_payload(payload)

    def set_html(self, in_html):
        """
        Replace HTML version of the email body. The plaintext version is unaffected.
        :param in_html: HTML email body, replaces old HTML email body
        """
        try:
            payload = self.msg.get_payload()
            payload[1] = MIMEText(in_html, 'html')
            self.msg.set_payload(payload)
        except TypeError:
            print("ERROR: "
                  "Payload is not a list. Specify an HTML message with in_htmltext in MailSender.set_message()")
            raise

    def set_recipients(self, in_recipients):
        """
        Sets the list of recipients' email addresses. This is used by the email sending functions.
        :param in_recipients: All recipients to whom the email should be sent (Must be a list, even when there is only one recipient)
        """
        if not isinstance(in_recipients, (list, tuple)):
            raise TypeError(
                "Recipients must be a list or tuple, is {}".format(type(in_recipients)))

        self.recipients = in_recipients

    def set_cc_bcc(self, cc, bcc):
        cc = []
        if self.msg.CC:
            if isinstance(self.msg.CC, str):
                cc = [self.msg.CC]
            else:
                cc = list(self.msg.CC)

        bcc = []
        if self.msg.BCC:
            if isinstance(self.msg.BCC, str):
                bcc = [self.msg.BCC]
            else:
                bcc = list(self.msg.BCC)

        self.recipients.append(cc)
        self.recipients.append(bcc)

    def add_recipient(self, in_recipient):
        """Adds a recipient to the back of the list
        :param in_recipient: Recipient email addresses
        """
        self.recipients.append(in_recipient)

    def connect(self):
        """
        Must be called before sending messages. Connects to SMTP server using the username and password.
        """
        if self.use_tls:
            self.smtpserver.starttls()
        self.smtpserver.login(self.username, self.password)
        self.connected = True
        print("Connected to {}".format(self.server_name))

    def disconnect(self):
        self.smtpserver.close()
        self.connected = False

    def send_all(self, close_connection=True):
        """Sends message to all specified recipients, one at a time. Optionally closes connection after sending. Close the connection after sending if you are not sending another batch of emails immediately after.
        :param close_connection: Should the connection to the server be closed after all emails have been sent (True) or not (False)
         """
        if not self.connected:
            raise ConnectionError(
                "Not connected to any server. Try self.connect() first")

        print("Message: {}".format(self.msg.get_payload()))

        for recipient in self.recipients:
            self.msg.replace_header("To", recipient)
            print("Sending to {}".format(recipient))
            self.smtpserver.send_message(self.msg)

        print("All messages sent")

        if close_connection:
            self.disconnect()
            print("Connection closed")
