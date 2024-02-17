from datetime import datetime, timedelta

from flask import request, flash, json, url_for, current_app, redirect, g
from flask_login import login_required, current_user
from flask_babel import _
from sqlalchemy import desc, or_, and_, text

from app import db, celery
from app.activitypub.signature import post_request
from app.chat.forms import AddReply
from app.models import AllowedInstances, BannedInstances, ActivityPubLog, utcnow, Site, Community, CommunityMember, \
    User, Instance, File, Report, Topic, UserRegistration, ChatMessage, Notification, InstanceBlock
from app.user.forms import ReportUserForm
from app.utils import render_template, permission_required, set_setting, get_setting, gibberish, markdown_to_html, \
    moderating_communities, joined_communities, finalize_user_setup, theme_list, allowlist_html, shorten_string
from app.chat import bp


@bp.route('/chat', methods=['GET', 'POST'])
@bp.route('/chat/<int:sender_id>', methods=['GET', 'POST'])
@login_required
def chat_home(sender_id=None):
    form = AddReply()
    if form.validate_on_submit():
        recipient = User.query.get(form.recipient_id.data)
        reply = ChatMessage(sender_id=current_user.id, recipient_id=recipient.id,
                            body=form.message.data, body_html=allowlist_html(markdown_to_html(form.message.data)))
        if recipient.is_local():
            # Notify local recipient
            notify = Notification(title=shorten_string('New message from ' + current_user.display_name()), url='/chat/' + str(current_user.id),
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
                    "published": utcnow().isoformat() + 'Z',    # Lemmy is inconsistent with the date format they use
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
                flash(_('Message failed to send to remote server. Try again later.'), 'error')

        return redirect(url_for('chat.chat_home', sender_id=recipient.id, _anchor=f'message_{reply.id}'))
    else:
        senders = User.query.filter(User.banned == False).join(ChatMessage, ChatMessage.sender_id == User.id)
        senders = senders.filter(ChatMessage.recipient_id == current_user.id).order_by(desc(ChatMessage.created_at)).limit(500).all()

        if senders:
            messages_with = senders[0].id if sender_id is None else sender_id
            sender_id = messages_with
            messages = ChatMessage.query.filter(or_(
                   and_(ChatMessage.recipient_id == current_user.id, ChatMessage.sender_id == messages_with),
                   and_(ChatMessage.recipient_id == messages_with,   ChatMessage.sender_id == current_user.id))
            )
            messages = messages.order_by(ChatMessage.created_at).all()
            if messages:
                if messages[0].sender_id == current_user.id:
                    other_party = User.query.get(messages[0].recipient_id)
                else:
                    other_party = User.query.get(messages[0].sender_id)
            else:
                other_party = None
            form.recipient_id.data = messages_with
        else:
            messages = []
            other_party = None
        if sender_id and int(sender_id):
            sql = f"UPDATE notification SET read = true WHERE url = '/chat/{sender_id}' AND user_id = {current_user.id}"
            db.session.execute(text(sql))
            db.session.commit()
            current_user.unread_notifications = Notification.query.filter_by(user_id=current_user.id, read=False).count()
            db.session.commit()

        return render_template('chat/home.html', title=_('Chat with %(name)s', name=other_party.display_name()) if other_party else _('Chat'),
                               senders=senders, messages=messages, other_party=other_party, form=form,
                               moderating_communities=moderating_communities(current_user.get_id()),
                               joined_communities=joined_communities(current_user.get_id()),
                               site=g.site)


@bp.route('/chat/<int:to>/new', methods=['GET', 'POST'])
@login_required
def new_message(to):
    recipient = User.query.get_or_404(to)
    existing_conversation = ChatMessage.query.filter(or_(
                   and_(ChatMessage.recipient_id == current_user.id, ChatMessage.sender_id == recipient.id),
                   and_(ChatMessage.recipient_id == recipient.id,   ChatMessage.sender_id == current_user.id))
            ).first()
    if existing_conversation:
        return redirect(url_for('chat.home', sender_id=recipient.id, _anchor='submit'))
    form = AddReply()
    if form.validate_on_submit():
        flash(_('Message sent'))
        return redirect(url_for('chat.home', sender_id=recipient.id))


@bp.route('/chat/<int:sender_id>/options', methods=['GET', 'POST'])
@login_required
def chat_options(sender_id):
    sender = User.query.get_or_404(sender_id)
    return render_template('chat/chat_options.html', sender=sender,
                           moderating_communities=moderating_communities(current_user.get_id()),
                           joined_communities=joined_communities(current_user.get_id()),
                           site=g.site
                           )


@bp.route('/chat/<int:sender_id>/delete', methods=['GET', 'POST'])
@login_required
def chat_delete(sender_id):
    sender = User.query.get_or_404(sender_id)
    ChatMessage.query.filter(or_(
        and_(ChatMessage.recipient_id == current_user.id, ChatMessage.sender_id == sender.id),
        and_(ChatMessage.recipient_id == sender.id, ChatMessage.sender_id == current_user.id))
    ).delete()
    db.session.commit()
    flash(_('Conversation deleted'))
    return redirect(url_for('chat.chat_home'))


@bp.route('/chat/<int:sender_id>/block_instance', methods=['GET', 'POST'])
@login_required
def block_instance(sender_id):
    sender = User.query.get_or_404(sender_id)
    existing = InstanceBlock.query.filter_by(user_id=current_user.id, instance_id=sender.instance_id).first()
    if not existing:
        db.session.add(InstanceBlock(user_id=current_user.id, instance_id=sender.instance_id))
        db.session.commit()
    flash(_('Instance blocked.'))
    return redirect(url_for('chat.chat_home'))


@bp.route('/chat/<int:sender_id>/report', methods=['GET', 'POST'])
@login_required
def chat_report(sender_id):
    sender = User.query.get_or_404(sender_id)
    form = ReportUserForm()
    if not sender.banned:
        if form.validate_on_submit():
            report = Report(reasons=form.reasons_to_string(form.reasons.data), description=form.description.data,
                            type=0, reporter_id=current_user.id, suspect_user_id=sender.id)
            db.session.add(report)

            # Notify site admin
            already_notified = set()
            for admin in Site.admins():
                if admin.id not in already_notified:
                    notify = Notification(title='Reported conversation with user', url='/admin/reports', user_id=admin.id,
                                          author_id=current_user.id)
                    db.session.add(notify)
                    admin.unread_notifications += 1
            sender.reports += 1
            db.session.commit()

            # todo: federate report to originating instance
            if not sender.is_local() and form.report_remote.data:
                ...

            flash(_('%(user_name)s has been reported, thank you!', user_name=sender.link()))
            goto = request.args.get('redirect') if 'redirect' in request.args else f'/u/{sender.link()}'
            return redirect(goto)
        elif request.method == 'GET':
            form.report_remote.data = True

    return render_template('user/user_report.html', title=_('Report user'), form=form, user=sender,
                           moderating_communities=moderating_communities(current_user.get_id()),
                           joined_communities=joined_communities(current_user.get_id())
                           )