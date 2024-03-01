from flask import request, flash, json, url_for, current_app, redirect, g
from flask_login import login_required, current_user
from flask_babel import _
from sqlalchemy import or_

from app.models import Post
from app.search import bp
from app.utils import moderating_communities, joined_communities, render_template, blocked_domains


@bp.route('/search', methods=['GET', 'POST'])
@login_required
def run_search():
    if request.args.get('q') is not None:
        q = request.args.get('q')
        page = request.args.get('page', 1, type=int)
        low_bandwidth = request.cookies.get('low_bandwidth', '0') == '1'

        posts = Post.query.search(q)
        if current_user.ignore_bots:
            posts = posts.filter(Post.from_bot == False)
        if current_user.show_nsfl is False:
            posts = posts.filter(Post.nsfl == False)
        if current_user.show_nsfw is False:
            posts = posts.filter(Post.nsfw == False)

        domains_ids = blocked_domains(current_user.id)
        if domains_ids:
            posts = posts.filter(or_(Post.domain_id.not_in(domains_ids), Post.domain_id == None))
        posts = posts.paginate(page=page, per_page=100 if current_user.is_authenticated and not low_bandwidth else 50,
                               error_out=False)

        next_url = url_for('search.run_search', page=posts.next_num, q=q) if posts.has_next else None
        prev_url = url_for('search.run_search', page=posts.prev_num, q=q) if posts.has_prev and page != 1 else None

        return render_template('search/results.html', title=_('Search results for %(q)s', q=q), posts=posts, q=q,
                               next_url=next_url, prev_url=prev_url,
                               moderating_communities=moderating_communities(current_user.get_id()),
                               joined_communities=joined_communities(current_user.get_id()),
                               site=g.site)

    else:
        return render_template('search/start.html', title=_('Search'),
                               moderating_communities=moderating_communities(current_user.get_id()),
                               joined_communities=joined_communities(current_user.get_id()),
                               site=g.site)
