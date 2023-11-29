from flask import redirect, url_for, flash, request, make_response, session, Markup, current_app, abort
from flask_login import login_user, logout_user, current_user, login_required
from flask_babel import _

from app import db, constants
from app.models import Post, Domain
from app.domain import bp
from app.utils import get_setting, render_template
from sqlalchemy import desc


@bp.route('/d/<domain_id>', methods=['GET'])
def show_domain(domain_id):
    if '.' in domain_id:
        domain = Domain.query.filter_by(name=domain_id, banned=False).first()
    else:
        domain = Domain.query.get_or_404(domain_id)
        if domain.banned:
            domain = None
    if domain:
        if current_user.is_anonymous or current_user.ignore_bots:
            posts = Post.query.filter(Post.from_bot == False, Post.domain_id == domain.id).order_by(desc(Post.last_active)).all()
        else:
            posts = Post.query.filter(Post.domain_id == domain.id).order_by(desc(Post.last_active)).all()
        return render_template('domain/domain.html', domain=domain, title=domain.name, posts=posts,
                               POST_TYPE_IMAGE=constants.POST_TYPE_IMAGE, POST_TYPE_LINK=constants.POST_TYPE_LINK)
    else:
        abort(404)


@bp.route('/domains', methods=['GET'])
def domains():
    domains = Domain.query.filter_by(banned=False).order_by(Domain.name).all()

    return render_template('domain/domains.html', title='All known domains', domains=domains)