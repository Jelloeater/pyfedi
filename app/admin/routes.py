from datetime import datetime, timedelta
from time import sleep

from flask import request, flash, json, url_for, current_app, redirect
from flask_login import login_required, current_user
from flask_babel import _
from sqlalchemy import text, desc

from app import db, celery
from app.activitypub.routes import process_inbox_request, process_delete_request
from app.activitypub.signature import post_request
from app.activitypub.util import default_context
from app.admin.forms import FederationForm, SiteMiscForm, SiteProfileForm, EditCommunityForm, EditUserForm, \
    EditTopicForm
from app.admin.util import unsubscribe_from_everything_then_delete, unsubscribe_from_community
from app.community.util import save_icon_file, save_banner_file
from app.models import AllowedInstances, BannedInstances, ActivityPubLog, utcnow, Site, Community, CommunityMember, \
    User, Instance, File, Report, Topic
from app.utils import render_template, permission_required, set_setting, get_setting, gibberish, markdown_to_html, \
    moderating_communities, joined_communities
from app.admin import bp


@bp.route('/', methods=['GET', 'POST'])
@login_required
@permission_required('change instance settings')
def admin_home():
    return render_template('admin/home.html', title=_('Admin'), moderating_communities=moderating_communities(current_user.get_id()),
                           joined_communities=joined_communities(current_user.get_id()))


@bp.route('/site', methods=['GET', 'POST'])
@login_required
@permission_required('change instance settings')
def admin_site():
    form = SiteProfileForm()
    site = Site.query.get(1)
    if site is None:
        site = Site()
    if form.validate_on_submit():
        site.name = form.name.data
        site.description = form.description.data
        site.sidebar = form.sidebar.data
        site.legal_information = form.legal_information.data
        site.updated = utcnow()
        if site.id is None:
            db.session.add(site)
        db.session.commit()
        flash('Settings saved.')
    elif request.method == 'GET':
        form.name.data = site.name
        form.description.data = site.description
        form.sidebar.data = site.sidebar
        form.legal_information.data = site.legal_information
    return render_template('admin/site.html', title=_('Site profile'), form=form,
                           moderating_communities=moderating_communities(current_user.get_id()),
                           joined_communities=joined_communities(current_user.get_id())
                           )


@bp.route('/misc', methods=['GET', 'POST'])
@login_required
@permission_required('change instance settings')
def admin_misc():
    form = SiteMiscForm()
    site = Site.query.get(1)
    if site is None:
        site = Site()
    if form.validate_on_submit():
        site.enable_downvotes = form.enable_downvotes.data
        site.allow_local_image_posts = form.allow_local_image_posts.data
        site.remote_image_cache_days = form.remote_image_cache_days.data
        site.enable_nsfw = form.enable_nsfw.data
        site.enable_nsfl = form.enable_nsfl.data
        site.community_creation_admin_only = form.community_creation_admin_only.data
        site.reports_email_admins = form.reports_email_admins.data
        site.registration_mode = form.registration_mode.data
        site.application_question = form.application_question.data
        site.log_activitypub_json = form.log_activitypub_json.data
        site.updated = utcnow()
        if site.id is None:
            db.session.add(site)
        db.session.commit()
        flash('Settings saved.')
    elif request.method == 'GET':
        form.enable_downvotes.data = site.enable_downvotes
        form.allow_local_image_posts.data = site.allow_local_image_posts
        form.remote_image_cache_days.data = site.remote_image_cache_days
        form.enable_nsfw.data = site.enable_nsfw
        form.enable_nsfl.data = site.enable_nsfl
        form.community_creation_admin_only.data = site.community_creation_admin_only
        form.reports_email_admins.data = site.reports_email_admins
        form.registration_mode.data = site.registration_mode
        form.application_question.data = site.application_question
        form.log_activitypub_json.data = site.log_activitypub_json
    return render_template('admin/misc.html', title=_('Misc settings'), form=form,
                           moderating_communities=moderating_communities(current_user.get_id()),
                           joined_communities=joined_communities(current_user.get_id())
                           )


@bp.route('/federation', methods=['GET', 'POST'])
@login_required
@permission_required('change instance settings')
def admin_federation():
    form = FederationForm()
    site = Site.query.get(1)
    if site is None:
        site = Site()
    # todo: finish form
    site.updated = utcnow()
    if form.validate_on_submit():
        if form.use_allowlist.data:
            set_setting('use_allowlist', True)
            db.session.execute(text('DELETE FROM allowed_instances'))
            for allow in form.allowlist.data.split('\n'):
                if allow.strip():
                    db.session.add(AllowedInstances(domain=allow.strip()))
        if form.use_blocklist.data:
            set_setting('use_allowlist', False)
            db.session.execute(text('DELETE FROM banned_instances'))
            for banned in form.blocklist.data.split('\n'):
                if banned.strip():
                    db.session.add(BannedInstances(domain=banned.strip()))
        db.session.commit()
        flash(_('Admin settings saved'))

    elif request.method == 'GET':
        form.use_allowlist.data = get_setting('use_allowlist', False)
        form.use_blocklist.data = not form.use_allowlist.data
        instances = BannedInstances.query.all()
        form.blocklist.data = '\n'.join([instance.domain for instance in instances])
        instances = AllowedInstances.query.all()
        form.allowlist.data = '\n'.join([instance.domain for instance in instances])

    return render_template('admin/federation.html', title=_('Federation settings'), form=form,
                           moderating_communities=moderating_communities(current_user.get_id()),
                           joined_communities=joined_communities(current_user.get_id())
                           )


@bp.route('/activities', methods=['GET'])
@login_required
@permission_required('change instance settings')
def admin_activities():
    db.session.query(ActivityPubLog).filter(
        ActivityPubLog.created_at < utcnow() - timedelta(days=3)).delete()
    db.session.commit()

    page = request.args.get('page', 1, type=int)

    activities = ActivityPubLog.query.order_by(desc(ActivityPubLog.created_at)).paginate(page=page, per_page=1000, error_out=False)

    next_url = url_for('admin.admin_activities', page=activities.next_num) if activities.has_next else None
    prev_url = url_for('admin.admin_activities', page=activities.prev_num) if activities.has_prev and page != 1 else None

    return render_template('admin/activities.html', title=_('ActivityPub Log'), next_url=next_url, prev_url=prev_url,
                           activities=activities)


@bp.route('/activity_json/<int:activity_id>')
@login_required
@permission_required('change instance settings')
def activity_json(activity_id):
    activity = ActivityPubLog.query.get_or_404(activity_id)
    return render_template('admin/activity_json.html', title=_('Activity JSON'),
                           activity_json_data=json.loads(activity.activity_json), activity=activity, current_app=current_app)


@bp.route('/activity_json/<int:activity_id>/replay')
@login_required
@permission_required('change instance settings')
def activity_replay(activity_id):
    activity = ActivityPubLog.query.get_or_404(activity_id)
    request_json = json.loads(activity.activity_json)
    if 'type' in request_json and request_json['type'] == 'Delete' and request_json['id'].endswith('#delete'):
        process_delete_request(request_json, activity.id, None)
    else:
        process_inbox_request(request_json, activity.id, None)
    return 'Ok'


@bp.route('/communities', methods=['GET'])
@login_required
@permission_required('administer all communities')
def admin_communities():

    page = request.args.get('page', 1, type=int)
    search = request.args.get('search', '')

    communities = Community.query.filter_by(banned=False)
    if search:
        communities = communities.filter(Community.title.ilike(f"%{search}%"))
    communities = communities.order_by(Community.title).paginate(page=page, per_page=1000, error_out=False)

    next_url = url_for('admin.admin_communities', page=communities.next_num) if communities.has_next else None
    prev_url = url_for('admin.admin_communities', page=communities.prev_num) if communities.has_prev and page != 1 else None

    return render_template('admin/communities.html', title=_('Communities'), next_url=next_url, prev_url=prev_url,
                           communities=communities, moderating_communities=moderating_communities(current_user.get_id()),
                           joined_communities=joined_communities(current_user.get_id()))


def topics_for_form():
    topics = Topic.query.order_by(Topic.name).all()
    result = [(0, _('None'))]
    for topic in topics:
        result.append((topic.id, topic.name))
    return result


def communities_for_form():
    communities = Community.query.order_by(Community.title).all()
    result = [(0, _('None'))]
    for community in communities:
        result.append((community.id, community.title))
    return result


@bp.route('/community/<int:community_id>/edit', methods=['GET', 'POST'])
@login_required
@permission_required('administer all communities')
def admin_community_edit(community_id):
    form = EditCommunityForm()
    community = Community.query.get_or_404(community_id)
    form.topic.choices = topics_for_form()
    if form.validate_on_submit():
        community.name = form.url.data
        community.title = form.title.data
        community.description = form.description.data
        community.description_html = markdown_to_html(form.description.data)
        community.rules = form.rules.data
        community.rules_html = markdown_to_html(form.rules.data)
        community.nsfw = form.nsfw.data
        community.local_only = form.local_only.data
        community.restricted_to_mods = form.restricted_to_mods.data
        community.new_mods_wanted = form.new_mods_wanted.data
        community.show_home = form.show_home.data
        community.show_popular = form.show_popular.data
        community.show_all = form.show_all.data
        community.low_quality = form.low_quality.data
        community.content_retention = form.content_retention.data
        community.topic_id = form.topic.data if form.topic.data != 0 else None
        community.default_layout = form.default_layout.data
        icon_file = request.files['icon_file']
        if icon_file and icon_file.filename != '':
            if community.icon_id:
                community.icon.delete_from_disk()
            file = save_icon_file(icon_file)
            if file:
                community.icon = file
        banner_file = request.files['banner_file']
        if banner_file and banner_file.filename != '':
            if community.image_id:
                community.image.delete_from_disk()
            file = save_banner_file(banner_file)
            if file:
                community.image = file

        db.session.commit()
        flash(_('Saved'))
        return redirect(url_for('admin.admin_communities'))
    else:
        if not community.is_local():
            flash(_('This is a remote community - most settings here will be regularly overwritten with data from the original server.'), 'warning')
        form.url.data = community.name
        form.title.data = community.title
        form.description.data = community.description
        form.rules.data = community.rules
        form.nsfw.data = community.nsfw
        form.local_only.data = community.local_only
        form.new_mods_wanted.data = community.new_mods_wanted
        form.restricted_to_mods.data = community.restricted_to_mods
        form.show_home.data = community.show_home
        form.show_popular.data = community.show_popular
        form.show_all.data = community.show_all
        form.low_quality.data = community.low_quality
        form.content_retention.data = community.content_retention
        form.topic.data = community.topic_id if community.topic_id else None
        form.default_layout.data = community.default_layout
    return render_template('admin/edit_community.html', title=_('Edit community'), form=form, community=community,
                           moderating_communities=moderating_communities(current_user.get_id()),
                           joined_communities=joined_communities(current_user.get_id())
                           )


@bp.route('/community/<int:community_id>/delete', methods=['GET'])
@login_required
@permission_required('administer all communities')
def admin_community_delete(community_id):
    community = Community.query.get_or_404(community_id)

    community.banned = True  # Unsubscribing everyone could take a long time so until that is completed hide this community from the UI by banning it.
    community.last_active = utcnow()
    db.session.commit()

    unsubscribe_everyone_then_delete(community.id)

    flash(_('Community deleted'))
    return redirect(url_for('admin.admin_communities'))


def unsubscribe_everyone_then_delete(community_id):
    if current_app.debug:
        unsubscribe_everyone_then_delete_task(community_id)
    else:
        unsubscribe_everyone_then_delete_task.delay(community_id)


@celery.task
def unsubscribe_everyone_then_delete_task(community_id):
    community = Community.query.get_or_404(community_id)
    if not community.is_local():
        members = CommunityMember.query.filter_by(community_id=community_id).all()
        for member in members:
            user = User.query.get(member.user_id)
            unsubscribe_from_community(community, user)
    else:
        # todo: federate delete of local community out to all following instances
        ...

    sleep(5)
    community.delete_dependencies()
    db.session.delete(community)    # todo: when a remote community is deleted it will be able to be re-created by using the 'Add remote' function. Not ideal. Consider soft-delete.
    db.session.commit()


@bp.route('/topics', methods=['GET'])
@login_required
@permission_required('administer all communities')
def admin_topics():
    topics = Topic.query.order_by(Topic.name).all()
    return render_template('admin/topics.html', title=_('Topics'), topics=topics,
                           moderating_communities=moderating_communities(current_user.get_id()),
                           joined_communities=joined_communities(current_user.get_id())
                           )


@bp.route('/topic/add', methods=['GET', 'POST'])
@login_required
@permission_required('administer all communities')
def admin_topic_add():
    form = EditTopicForm()
    form.add_community.choices = communities_for_form()
    if form.validate_on_submit():
        topic = Topic(name=form.name.data, num_communities=0)
        db.session.add(topic)
        db.session.commit()
        if form.add_community.data:
            community = Community.query.get(form.add_community.data)
            community.topic_id = topic.id
            topic.num_communities += 1
            db.session.commit()
        flash(_('Saved'))
        return redirect(url_for('admin.admin_topics'))

    return render_template('admin/edit_topic.html', title=_('Add topic'), form=form,
                           moderating_communities=moderating_communities(current_user.get_id()),
                           joined_communities=joined_communities(current_user.get_id())
                           )

@bp.route('/topic/<int:topic_id>/edit', methods=['GET', 'POST'])
@login_required
@permission_required('administer all communities')
def admin_topic_edit(topic_id):
    form = EditTopicForm()
    topic = Topic.query.get_or_404(topic_id)
    form.add_community.choices = communities_for_form()
    if form.validate_on_submit():
        topic.name = form.name.data
        topic.num_communities = topic.communities.count() + 1
        if form.add_community.data:
            community = Community.query.get(form.add_community.data)
            community.topic_id = topic.id
        db.session.commit()
        flash(_('Saved'))
        return redirect(url_for('admin.admin_topics'))
    else:
        form.name.data = topic.name
    return render_template('admin/edit_topic.html', title=_('Edit topic'), form=form, topic=topic,
                           moderating_communities=moderating_communities(current_user.get_id()),
                           joined_communities=joined_communities(current_user.get_id())
                           )


@bp.route('/topic/<int:topic_id>/delete', methods=['GET'])
@login_required
@permission_required('administer all communities')
def admin_topic_delete(topic_id):
    topic = Topic.query.get_or_404(topic_id)
    topic.num_communities = topic.communities.count()
    if topic.num_communities == 0:
        db.session.delete(topic)
        flash(_('Topic deleted'))
    else:
        flash(_('Cannot delete topic with communities assigned to it.', 'error'))
    db.session.commit()

    return redirect(url_for('admin.admin_topics'))


@bp.route('/users', methods=['GET'])
@login_required
@permission_required('administer all users')
def admin_users():

    page = request.args.get('page', 1, type=int)
    search = request.args.get('search', '')
    local_remote = request.args.get('local_remote', '')

    users = User.query.filter_by(deleted=False)
    if local_remote == 'local':
        users = users.filter_by(ap_id=None)
    if local_remote == 'remote':
        users = users.filter(User.ap_id != None)
    if search:
        users = users.filter(User.email.ilike(f"%{search}%"))
    users = users.order_by(User.user_name).paginate(page=page, per_page=1000, error_out=False)

    next_url = url_for('admin.admin_users', page=users.next_num) if users.has_next else None
    prev_url = url_for('admin.admin_users', page=users.prev_num) if users.has_prev and page != 1 else None

    return render_template('admin/users.html', title=_('Users'), next_url=next_url, prev_url=prev_url, users=users,
                           local_remote=local_remote, search=search,
                           moderating_communities=moderating_communities(current_user.get_id()),
                           joined_communities=joined_communities(current_user.get_id())
                           )


@bp.route('/user/<int:user_id>/edit', methods=['GET', 'POST'])
@login_required
@permission_required('administer all users')
def admin_user_edit(user_id):
    form = EditUserForm()
    user = User.query.get_or_404(user_id)
    if form.validate_on_submit():
        user.about = form.about.data
        user.about_html = markdown_to_html(form.about.data)
        user.matrix_user_id = form.matrix_user_id.data
        user.bot = form.bot.data
        profile_file = request.files['profile_file']
        if profile_file and profile_file.filename != '':
            # remove old avatar
            if user.avatar_id:
                file = File.query.get(user.avatar_id)
                file.delete_from_disk()
                user.avatar_id = None
                db.session.delete(file)

            # add new avatar
            file = save_icon_file(profile_file, 'users')
            if file:
                user.avatar = file
        banner_file = request.files['banner_file']
        if banner_file and banner_file.filename != '':
            # remove old cover
            if user.cover_id:
                file = File.query.get(user.cover_id)
                file.delete_from_disk()
                user.cover_id = None
                db.session.delete(file)

            # add new cover
            file = save_banner_file(banner_file, 'users')
            if file:
                user.cover = file
        user.newsletter = form.newsletter.data
        user.ignore_bots = form.ignore_bots.data
        user.show_nsfw = form.nsfw.data
        user.show_nsfl = form.nsfl.data
        user.searchable = form.searchable.data
        user.indexable = form.indexable.data
        user.ap_manually_approves_followers = form.manually_approves_followers.data
        db.session.commit()
        user.flush_cache()
        flash(_('Saved'))
        return redirect(url_for('admin.admin_users'))
    else:
        if not user.is_local():
            flash(_('This is a remote user - most settings here will be regularly overwritten with data from the original server.'), 'warning')
        form.about.data = user.about
        form.matrix_user_id.data = user.matrix_user_id
        form.newsletter.data = user.newsletter
        form.bot.data = user.bot
        form.ignore_bots.data = user.ignore_bots
        form.nsfw.data = user.show_nsfw
        form.nsfl.data = user.show_nsfl
        form.searchable.data = user.searchable
        form.indexable.data = user.indexable
        form.manually_approves_followers.data = user.ap_manually_approves_followers

    return render_template('admin/edit_user.html', title=_('Edit user'), form=form, user=user,
                           moderating_communities=moderating_communities(current_user.get_id()),
                           joined_communities=joined_communities(current_user.get_id())
                           )


@bp.route('/user/<int:user_id>/delete', methods=['GET'])
@login_required
@permission_required('administer all users')
def admin_user_delete(user_id):
    user = User.query.get_or_404(user_id)

    user.banned = True  # Unsubscribing everyone could take a long time so until that is completed hide this user from the UI by banning it.
    user.last_active = utcnow()
    db.session.commit()

    if user.is_local():
        unsubscribe_from_everything_then_delete(user.id)
    else:
        user.deleted = True
        user.delete_dependencies()
        db.session.commit()

    flash(_('User deleted'))
    return redirect(url_for('admin.admin_users'))


@bp.route('/reports', methods=['GET'])
@login_required
@permission_required('administer all users')
def admin_reports():

    page = request.args.get('page', 1, type=int)
    search = request.args.get('search', '')
    local_remote = request.args.get('local_remote', '')

    reports = Report.query.filter_by(status=0)
    if local_remote == 'local':
        reports = reports.filter_by(ap_id=None)
    if local_remote == 'remote':
        reports = reports.filter(Report.ap_id != None)
    reports = reports.order_by(desc(Report.created_at)).paginate(page=page, per_page=1000, error_out=False)

    next_url = url_for('admin.admin_reports', page=reports.next_num) if reports.has_next else None
    prev_url = url_for('admin.admin_reports', page=reports.prev_num) if reports.has_prev and page != 1 else None

    return render_template('admin/reports.html', title=_('Reports'), next_url=next_url, prev_url=prev_url, reports=reports,
                           local_remote=local_remote, search=search,
                           moderating_communities=moderating_communities(current_user.get_id()),
                           joined_communities=joined_communities(current_user.get_id())
                           )