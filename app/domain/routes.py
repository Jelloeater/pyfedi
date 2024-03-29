from random import randint

from flask import redirect, url_for, flash, request, make_response, session, Markup, current_app, abort
from flask_login import login_user, logout_user, current_user, login_required
from flask_babel import _

from app import db, constants, cache
from app.inoculation import inoculation
from app.models import Post, Domain, Community, DomainBlock
from app.domain import bp
from app.utils import render_template, permission_required, joined_communities, moderating_communities, \
    user_filters_posts, blocked_domains, blocked_instances
from sqlalchemy import desc, or_


@bp.route('/d/<domain_id>', methods=['GET'])
def show_domain(domain_id):
    page = request.args.get('page', 1, type=int)

    if '.' in domain_id:
        domain = Domain.query.filter_by(name=domain_id, banned=False).first()
    else:
        domain = Domain.query.get_or_404(domain_id)
        if domain.banned:
            domain = None
    if domain:
        if current_user.is_anonymous or current_user.ignore_bots:
            posts = Post.query.join(Community, Community.id == Post.community_id).\
                filter(Post.from_bot == False, Post.domain_id == domain.id, Community.banned == False).\
                order_by(desc(Post.posted_at))
        else:
            posts = Post.query.join(Community).filter(Post.domain_id == domain.id, Community.banned == False).order_by(desc(Post.posted_at))

        if current_user.is_authenticated:
            instance_ids = blocked_instances(current_user.id)
            if instance_ids:
                posts = posts.filter(or_(Post.instance_id.not_in(instance_ids), Post.instance_id == None))
            content_filters = user_filters_posts(current_user.id)
        else:
            content_filters = {}
        # pagination
        posts = posts.paginate(page=page, per_page=100, error_out=False)
        next_url = url_for('domain.show_domain', domain_id=domain_id, page=posts.next_num) if posts.has_next else None
        prev_url = url_for('domain.show_domain', domain_id=domain_id, page=posts.prev_num) if posts.has_prev and page != 1 else None
        return render_template('domain/domain.html', domain=domain, title=domain.name, posts=posts,
                               POST_TYPE_IMAGE=constants.POST_TYPE_IMAGE, POST_TYPE_LINK=constants.POST_TYPE_LINK,
                               next_url=next_url, prev_url=prev_url,
                               content_filters=content_filters,
                               moderating_communities=moderating_communities(current_user.get_id()),
                               joined_communities=joined_communities(current_user.get_id()),
                               inoculation=inoculation[randint(0, len(inoculation) - 1)]
                               )
    else:
        abort(404)


@bp.route('/domains', methods=['GET'])
def domains():
    page = request.args.get('page', 1, type=int)
    search = request.args.get('search', '')

    domains = Domain.query.filter_by(banned=False)
    if search != '':
        domains = domains.filter(Domain.name.ilike(f'%{search}%'))
    domains = domains.order_by(Domain.name)
    domains = domains.paginate(page=page, per_page=100, error_out=False)

    ban_visibility_permission = False

    if not current_user.is_anonymous:
        if not current_user.created_recently() and current_user.reputation > 100 or current_user.is_admin():
            ban_visibility_permission = True

    next_url = url_for('domain.domains', page=domains.next_num) if domains.has_next else None
    prev_url = url_for('domain.domains', page=domains.prev_num) if domains.has_prev and page != 1 else None

    return render_template('domain/domains.html', title='All known domains', domains=domains,
                           next_url=next_url, prev_url=prev_url, search=search, ban_visibility_permission=ban_visibility_permission)


@bp.route('/domains/banned', methods=['GET'])
@login_required
def domains_blocked_list():
    if not current_user.trustworthy():
        abort(404)

    page = request.args.get('page', 1, type=int)
    search = request.args.get('search', '')

    domains = Domain.query.filter_by(banned=True)
    if search != '':
        domains = domains.filter(Domain.name.ilike(f'%{search}%'))
    domains = domains.order_by(Domain.name)
    domains = domains.paginate(page=page, per_page=100, error_out=False)

    next_url = url_for('domain.domains', page=domains.next_num) if domains.has_next else None
    prev_url = url_for('domain.domains', page=domains.prev_num) if domains.has_prev and page != 1 else None

    return render_template('domain/domains_blocked.html', title='Domains blocked on this instance', domains=domains,
                           next_url=next_url, prev_url=prev_url, search=search)


@bp.route('/d/<int:domain_id>/block')
@login_required
def domain_block(domain_id):
    domain = Domain.query.get_or_404(domain_id)
    block = DomainBlock.query.filter_by(user_id=current_user.id, domain_id=domain_id).first()
    if not block:
        block = DomainBlock(user_id=current_user.id, domain_id=domain_id)
        db.session.add(block)
        db.session.commit()
    cache.delete_memoized(blocked_domains, current_user.id)
    flash(_('%(name)s blocked.', name=domain.name))
    return redirect(url_for('domain.show_domain', domain_id=domain.id))


@bp.route('/d/<int:domain_id>/unblock')
@login_required
def domain_unblock(domain_id):
    domain = Domain.query.get_or_404(domain_id)
    block = DomainBlock.query.filter_by(user_id=current_user.id, domain_id=domain_id).first()
    if block:
        db.session.delete(block)
        db.session.commit()
    cache.delete_memoized(blocked_domains, current_user.id)
    flash(_('%(name)s un-blocked.', name=domain.name))
    return redirect(url_for('domain.show_domain', domain_id=domain.id))


@bp.route('/d/<int:domain_id>/ban')
@login_required
@permission_required('manage users')
def domain_ban(domain_id):
    domain = Domain.query.get_or_404(domain_id)
    if domain:
        domain.banned = True
        db.session.commit()
        domain.purge_content()
        flash(_('%(name)s banned for all users and all content deleted.', name=domain.name))
        return redirect(url_for('domain.domains'))


@bp.route('/d/<int:domain_id>/unban')
@login_required
@permission_required('manage users')
def domain_unban(domain_id):
    domain = Domain.query.get_or_404(domain_id)
    if domain:
        domain.banned = False
        db.session.commit()
        flash(_('%(name)s un-banned for all users.', name=domain.name))
        return redirect(url_for('domain.show_domain', domain_id=domain.id))
