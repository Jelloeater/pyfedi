from flask import request, flash, json, url_for, current_app, redirect, g, abort
from flask_login import login_required, current_user
from flask_babel import _
from sqlalchemy import desc, or_, and_, text

from app import db, celery
from app.chat.forms import AddReply, ReportConversationForm
from app.chat.util import send_message
from app.models import Site, User, Report, ChatMessage, Notification, InstanceBlock, Conversation, conversation_member
from app.user.forms import ReportUserForm
from app.utils import render_template, moderating_communities, joined_communities
from app.chat import bp


@bp.route('/chat', methods=['GET', 'POST'])
@bp.route('/chat/<int:conversation_id>', methods=['GET', 'POST'])
@login_required
def chat_home(conversation_id=None):
    form = AddReply()
    if form.validate_on_submit():
        reply = send_message(form, conversation_id)
        return redirect(url_for('chat.chat_home', conversation_id=conversation_id, _anchor=f'message_{reply.id}'))
    else:
        conversations = Conversation.query.join(conversation_member,
                                                conversation_member.c.conversation_id == Conversation.id). \
            filter(conversation_member.c.user_id == current_user.id).order_by(desc(Conversation.updated_at)).limit(50).all()
        if conversation_id is None:
            return redirect(url_for('chat.chat_home', conversation_id=conversations[0].id))
        else:
            conversation = Conversation.query.get_or_404(conversation_id)
            conversation.read = True
            if not current_user.is_admin() and not conversation.is_member(current_user):
                abort(400)
            if conversations:
                messages = conversation.messages.order_by(ChatMessage.created_at).all()
                if messages:
                    if messages[0].sender_id == current_user.id:
                        other_party = User.query.get(messages[0].recipient_id)
                    else:
                        other_party = User.query.get(messages[0].sender_id)
                else:
                    other_party = None
            else:
                messages = []
                other_party = None

            sql = f"UPDATE notification SET read = true WHERE url = '/chat/{conversation_id}' AND user_id = {current_user.id}"
            db.session.execute(text(sql))
            db.session.commit()
            current_user.unread_notifications = Notification.query.filter_by(user_id=current_user.id, read=False).count()
            db.session.commit()

            return render_template('chat/conversation.html', title=_('Chat with %(name)s', name=other_party.display_name()) if other_party else _('Chat'),
                                   conversations=conversations, messages=messages, form=form,
                                   current_conversation=conversation_id, conversation=conversation,
                                   moderating_communities=moderating_communities(current_user.get_id()),
                                   joined_communities=joined_communities(current_user.get_id()),
                                   site=g.site)


@bp.route('/chat/<int:to>/new', methods=['GET', 'POST'])
@login_required
def new_message(to):
    recipient = User.query.get_or_404(to)
    if current_user.created_recently() or current_user.reputation < 10 or current_user.banned or not current_user.verified:
        return redirect(url_for('chat.denied'))
    if recipient.has_blocked_user(current_user.id) or current_user.has_blocked_user(recipient.id):
        return redirect(url_for('chat.blocked'))
    existing_conversation = Conversation.find_existing_conversation(recipient=recipient, sender=current_user)
    if existing_conversation:
        return redirect(url_for('chat.chat_home', conversation_id=existing_conversation.id, _anchor='message'))
    form = AddReply()
    form.submit.label.text = _('Send')
    if form.validate_on_submit():
        conversation = Conversation(user_id=current_user.id)
        conversation.members.append(recipient)
        conversation.members.append(current_user)
        db.session.add(conversation)
        db.session.commit()
        reply = send_message(form, conversation.id)
        return redirect(url_for('chat.chat_home', conversation_id=conversation.id, _anchor=f'message_{reply.id}'))
    else:
        return render_template('chat/new_message.html', form=form, title=_('New message to "%(recipient_name)s"', recipient_name=recipient.link()),
                               recipient=recipient,
                               moderating_communities=moderating_communities(current_user.get_id()),
                               joined_communities=joined_communities(current_user.get_id()),
                               site=g.site)


@bp.route('/chat/denied', methods=['GET'])
@login_required
def denied():
    return render_template('chat/denied.html')


@bp.route('/chat/blocked', methods=['GET'])
@login_required
def blocked():
    return render_template('chat/blocked.html')


@bp.route('/chat/<int:conversation_id>/options', methods=['GET', 'POST'])
@login_required
def chat_options(conversation_id):
    conversation = Conversation.query.get_or_404(conversation_id)
    if current_user.is_admin() or current_user.is_member(current_user):
        return render_template('chat/chat_options.html', conversation=conversation,
                           moderating_communities=moderating_communities(current_user.get_id()),
                           joined_communities=joined_communities(current_user.get_id()),
                           site=g.site
                           )


@bp.route('/chat/<int:conversation_id>/delete', methods=['GET', 'POST'])
@login_required
def chat_delete(conversation_id):
    conversation = Conversation.query.get_or_404(conversation_id)
    if current_user.is_admin() or current_user.is_member(current_user):
        Report.query.filter(Report.suspect_conversation_id == conversation.id).delete()
        db.session.delete(conversation)
        db.session.commit()
        flash(_('Conversation deleted'))
    return redirect(url_for('chat.chat_home'))


@bp.route('/chat/<int:instance_id>/block_instance', methods=['GET', 'POST'])
@login_required
def block_instance(instance_id):
    existing = InstanceBlock.query.filter_by(user_id=current_user.id, instance_id=instance_id).first()
    if not existing:
        db.session.add(InstanceBlock(user_id=current_user.id, instance_id=instance_id))
        db.session.commit()
    flash(_('Instance blocked.'))
    return redirect(url_for('chat.chat_home'))


@bp.route('/chat/<int:conversation_id>/report', methods=['GET', 'POST'])
@login_required
def chat_report(conversation_id):
    conversation = Conversation.query.get_or_404(conversation_id)
    if current_user.is_admin() or current_user.is_member(current_user):
        form = ReportConversationForm()

        if form.validate_on_submit():
            report = Report(reasons=form.reasons_to_string(form.reasons.data), description=form.description.data,
                            type=4, reporter_id=current_user.id, suspect_conversation_id=conversation_id)
            db.session.add(report)

            # Notify site admin
            already_notified = set()
            for admin in Site.admins():
                if admin.id not in already_notified:
                    notify = Notification(title='Reported conversation with user', url='/admin/reports', user_id=admin.id,
                                          author_id=current_user.id)
                    db.session.add(notify)
                    admin.unread_notifications += 1
            db.session.commit()

            # todo: federate report to originating instance
            if form.report_remote.data:
                ...

            flash(_('This conversation has been reported, thank you!'))
            return redirect(url_for('chat.chat_home', conversation_id=conversation_id))
        elif request.method == 'GET':
            form.report_remote.data = True

        return render_template('chat/report.html', title=_('Report conversation'), form=form, conversation=conversation,
                               moderating_communities=moderating_communities(current_user.get_id()),
                               joined_communities=joined_communities(current_user.get_id())
                               )
