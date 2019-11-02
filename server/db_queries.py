from sqlalchemy.sql import func
from sqlalchemy.sql.expression import literal_column
from sqlalchemy.types import Unicode
from db_models import *


def child_rel_query(post_id, page=0, sort_by='top'):
    if sort_by == 'top':
        counts = db.session.query(Vote.rel_id, func.sum(Vote.value)\
                           .label('votecount'))\
                           .group_by(Vote.rel_id).subquery()

        rels_count = db.session.query(Relation, counts.c.votecount)\
                               .filter(Relation.parent_id==post_id)\
                               .outerjoin(counts, Relation.id==counts.c.rel_id)\
                               .order_by(func.coalesce(counts.c.votecount, 0).desc(),
                                         Relation.id)\
                               .slice(page*8, (page+1) * 8)
        rels = [rel_count[0] for rel_count in rels_count]
    else:
        rels = db.session.query(Relation)\
                         .order_by(Relation.time_linked.desc())\
                         .filter(Relation.parent_id==post_id)\
                         .slice(page*8, (page+1) * 8).all()
    return rels

def actions_query(post_id):
    dbq = db.session
    comments = dbq.query(Comment.id, Comment.time_posted.label("time"),
                         literal_column("'Comment'", Unicode).label("t"))\
                  .filter(Comment.post_id==post_id)
    rels = dbq.query(Relation.id, Relation.time_linked.label("time"),
                     literal_column("'Relation'", Unicode).label("t"))\
              .filter(Relation.parent_id==post_id)
    q = comments.union(rels)
    return q

def post_actions(post_id, page=1):
    page = 1 if not page else page
    actions = actions_query(post_id).order_by("time")\
                                   .slice((page-1)*20, page*20).all()
    # should add the functionality to query the edits as well
    return [[action[0], action[2]] for action in actions]

def total_actions(post_id):
    return int(actions_query(post_id).count())
