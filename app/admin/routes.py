from datetime import datetime, timedelta

from flask import request, flash, json, url_for
from flask_login import login_required, current_user
from flask_babel import _
from sqlalchemy import text, desc

from app import db
from app.admin.forms import FederationForm, SiteMiscForm, SiteProfileForm
from app.models import AllowedInstances, BannedInstances, ActivityPubLog, utcnow, Site
from app.utils import render_template, permission_required, set_setting, get_setting
from app.admin import bp


@bp.route('/', methods=['GET', 'POST'])
@login_required
@permission_required('change instance settings')
def admin_home():
    return render_template('admin/home.html', title=_('Admin'))


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
    return render_template('admin/site.html', title=_('Site profile'), form=form)


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
    return render_template('admin/misc.html', title=_('Misc settings'), form=form)


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

    return render_template('admin/federation.html', title=_('Federation settings'), form=form)


@bp.route('/activities', methods=['GET'])
@login_required
@permission_required('change instance settings')
def admin_activities():
    db.session.query(ActivityPubLog).filter(
        ActivityPubLog.created_at < utcnow() - timedelta(days=3)).delete()
    db.session.commit()

    page = request.args.get('page', 1, type=int)

    activities = ActivityPubLog.query.order_by(desc(ActivityPubLog.created_at)).paginate(page=page, per_page=1000, error_out=False)

    next_url = url_for('admin.admin_activities',
                       page=activities.next_num) if activities.has_next else None
    prev_url = url_for('admin.admin_activities',
                       page=activities.prev_num) if activities.has_prev and page != 1 else None

    return render_template('admin/activities.html', title=_('ActivityPub Log'), next_url=next_url, prev_url=prev_url,
                           activities=activities)


@bp.route('/activity_json/<int:activity_id>')
@login_required
@permission_required('change instance settings')
def activity_json(activity_id):
    activity = ActivityPubLog.query.get_or_404(activity_id)
    return render_template('admin/activity_json.html', title=_('Activity JSON'),
                           activity_json_data=json.loads(activity.activity_json))
