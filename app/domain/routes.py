from random import randint

from flask import redirect, url_for, flash, request, make_response, session, Markup, current_app, abort
from flask_login import login_user, logout_user, current_user, login_required
from flask_babel import _

from app import db, constants
from app.inoculation import inoculation
from app.models import Post, Domain, Community, DomainBlock
from app.domain import bp
from app.utils import get_setting, render_template, permission_required, joined_communities, moderating_communities, \
    user_filters_posts
from sqlalchemy import desc


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
                order_by(desc(Post.posted_at)).all()
        else:
            posts = Post.query.join(Community).filter(Post.domain_id == domain.id, Community.banned == False).order_by(desc(Post.posted_at))

        if current_user.is_authenticated:
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

    next_url = url_for('domain.domains', page=domains.next_num) if domains.has_next else None
    prev_url = url_for('domain.domains', page=domains.prev_num) if domains.has_prev and page != 1 else None

    return render_template('domain/domains.html', title='All known domains', domains=domains,
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
    flash(_('%(name)s blocked.', name=domain.name))
    return redirect(url_for('domain.show_domain', domain_id=domain.id))


@bp.route('/d/<int:domain_id>/unblock')
@login_required
def domain_unblock(domain_id):
    domain = Domain.query.get_or_404(domain_id)
    block = DomainBlock.query.filter_by(user_id=current_user.id, domain_id=domain_id).first()
    if not block:
        db.session.delete(block)
        db.session.commit()
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
        domain.banned = True
        db.session.commit()
        flash(_('%(name)s un-banned for all users.', name=domain.name))
        return redirect(url_for('domain.show_domain', domain_id=domain.id))
