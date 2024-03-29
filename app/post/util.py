from typing import List

from flask_login import current_user
from sqlalchemy import desc, text, or_

from app import db
from app.models import PostReply
from app.utils import blocked_instances


# replies to a post, in a tree, sorted by a variety of methods
def post_replies(post_id: int, sort_by: str, show_first: int = 0) -> List[PostReply]:
    comments = PostReply.query.filter_by(post_id=post_id)
    if current_user.is_authenticated:
        instance_ids = blocked_instances(current_user.id)
        if instance_ids:
            comments = comments.filter(or_(PostReply.instance_id.not_in(instance_ids), PostReply.instance_id == None))
    if sort_by == 'hot':
        comments = comments.order_by(desc(PostReply.ranking))
    elif sort_by == 'top':
        comments = comments.order_by(desc(PostReply.score))
    elif sort_by == 'new':
        comments = comments.order_by(desc(PostReply.posted_at))

    comments = comments.limit(2000) # paginating indented replies is too hard so just get the first 2000.

    comments_dict = {comment.id: {'comment': comment, 'replies': []} for comment in comments.all()}

    for comment in comments:
        if comment.parent_id is not None:
            parent_comment = comments_dict.get(comment.parent_id)
            if parent_comment:
                parent_comment['replies'].append(comments_dict[comment.id])

    return [comment for comment in comments_dict.values() if comment['comment'].parent_id is None]


def get_comment_branch(post_id: int, comment_id: int, sort_by: str) -> List[PostReply]:
    # Fetch the specified parent comment and its replies
    parent_comment = PostReply.query.get(comment_id)
    if parent_comment is None:
        return []

    comments = PostReply.query.filter(PostReply.post_id == post_id)
    if current_user.is_authenticated:
        instance_ids = blocked_instances(current_user.id)
        if instance_ids:
            comments = comments.filter(or_(PostReply.instance_id.not_in(instance_ids), PostReply.instance_id == None))
    if sort_by == 'hot':
        comments = comments.order_by(desc(PostReply.ranking))
    elif sort_by == 'top':
        comments = comments.order_by(desc(PostReply.score))
    elif sort_by == 'new':
        comments = comments.order_by(desc(PostReply.posted_at))

    comments_dict = {comment.id: {'comment': comment, 'replies': []} for comment in comments.all()}

    for comment in comments:
        if comment.parent_id is not None:
            parent_comment = comments_dict.get(comment.parent_id)
            if parent_comment:
                parent_comment['replies'].append(comments_dict[comment.id])

    return [comment for comment in comments_dict.values() if comment['comment'].id == comment_id]


# The number of replies a post has
def post_reply_count(post_id) -> int:
    return db.session.execute(text('SELECT COUNT(id) as c FROM "post_reply" WHERE post_id = :post_id'),
                              {'post_id': post_id}).scalar()
