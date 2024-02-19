from flask import flash, current_app
from flask_login import current_user
from flask_babel import _
from sqlalchemy import text

from app import db
from app.activitypub.signature import post_request
from app.models import User, ChatMessage, Notification, utcnow, Conversation
from app.utils import allowlist_html, shorten_string, gibberish, markdown_to_html


def send_message(form, conversation_id: int) -> ChatMessage:
    conversation = Conversation.query.get(conversation_id)
    reply = ChatMessage(sender_id=current_user.id, conversation_id=conversation.id,
                        body=form.message.data, body_html=allowlist_html(markdown_to_html(form.message.data)))
    for recipient in conversation.members:
        if recipient.id != current_user.id:
            if recipient.is_local():
                # Notify local recipient
                notify = Notification(title=shorten_string('New message from ' + current_user.display_name()),
                                      url='/chat/' + str(conversation_id),
                                      user_id=recipient.id,
                                      author_id=current_user.id)
                db.session.add(notify)
                recipient.unread_notifications += 1
                db.session.add(reply)
                db.session.commit()
            else:
                db.session.add(reply)
                db.session.commit()
                # Federate reply
                reply_json = {
                    "actor": current_user.profile_id(),
                    "id": f"https://{current_app.config['SERVER_NAME']}/activities/create/{gibberish(15)}",
                    "object": {
                        "attributedTo": current_user.profile_id(),
                        "content": reply.body_html,
                        "id": f"https://{current_app.config['SERVER_NAME']}/private_message/{reply.id}",
                        "mediaType": "text/html",
                        "published": utcnow().isoformat() + 'Z',  # Lemmy is inconsistent with the date format they use
                        "source": {
                            "content": reply.body,
                            "mediaType": "text/markdown"
                        },
                        "to": [
                            recipient.profile_id()
                        ],
                        "type": "ChatMessage"
                    },
                    "to": [
                        recipient.profile_id()
                    ],
                    "type": "Create"
                }
                success = post_request(recipient.ap_inbox_url, reply_json, current_user.private_key,
                                       current_user.profile_id() + '#main-key')
                if not success:
                    flash(_('Message failed to send to %(name)s.', name=recipient.link()), 'error')

    flash(_('Message sent.'))
    return reply


def find_existing_conversation(recipient, sender):
    sql = """SELECT 
                c.id AS conversation_id, 
                c.created_at AS conversation_created_at, 
                c.updated_at AS conversation_updated_at, 
                cm1.user_id AS user1_id, 
                cm2.user_id AS user2_id 
            FROM 
                public.conversation AS c 
            JOIN 
                public.conversation_member AS cm1 ON c.id = cm1.conversation_id 
            JOIN 
                public.conversation_member AS cm2 ON c.id = cm2.conversation_id 
            WHERE 
                cm1.user_id = :user_id_1 AND 
                cm2.user_id = :user_id_2 AND 
                cm1.user_id <> cm2.user_id;"""
    ec = db.session.execute(text(sql), {'user_id_1': recipient.id, 'user_id_2': sender.id}).fetchone()
    return Conversation.query.get(ec[0]) if ec else None
