from flask import Blueprint, Flask, request, session, g, redirect, url_for, abort, \
     render_template, flash, jsonify
from db_models import User, Post, Relation, Comment, Vote
from db_queries import child_rel_query, post_actions, total_actions
from utils import is_number, route_from
from transit.writer import Writer
from transit.reader import Reader
from io import StringIO, BytesIO
from localsettings import SETTINGS
from six import string_types
import math
from flask_login import login_user, logout_user, login_required, current_user
from sqlalchemy.orm.exc import NoResultFound

blueprint = Blueprint('views', __name__)

ACTIONS_PER_PAGE = 20

def transitify(val, format='json'):
    io = StringIO()
    writer = Writer(io, format) # or "json-verbose", "msgpack"
    writer.write(val)
    return io.getvalue()

def writable_current_user():
    if not current_user.is_anonymous:
        return current_user.writeable
    return None

def dict_by_id(alist, key="id"):
    return dict([(item[key], item) for item in alist])

def actions_with_data(post_id, page):
    actions = post_actions(post_id, page=int(page))
    posts = []
    rels = [(a[0]) for a in actions if a[1] == "Relation"]
    if rels:
        rels = Relation.query.filter(Relation.id.in_(rels))
        posts = Post.query.filter(
            Post.id.in_([r.child_id for r in rels]))
    comments = [(a[0]) for a in actions if a[1] == "Comment"]
    if comments:
        comments = Comment.query.filter(Comment.id.in_(comments))
    return {
        "actions": actions, 
        "rels": [r.writeable_with_vote_info(current_user) for r in rels], 
        "posts": [p.writeable for p in posts], 
        "comments": [c.writeable for c in comments],
        "page": int(page)
    }

def handle_asks(post, list_of_wants, page=None):
    post = Post.query.filter(Post.id==post).one() if isinstance(post, int) else post
    ret = {"current_post": post.id, "rels": {}, "posts": {}}
    if "children" in list_of_wants:
        rels = child_rel_query(post.id)
        child_ids = [rel.child_id for rel in rels]
        children = []
        if child_ids:
            children = Post.query.filter(Post.id.in_(child_ids)).all()
        child_posts = [p.writeable for p in children]
        ret["link_ids"] = [r.id for r in rels]
        rels = [r.writeable_with_vote_info(current_user) for r in rels]
        ret["posts"].update(dict_by_id(child_posts + [post.writeable]))
        ret["rels"].update(dict_by_id(rels))

    if "actions" in list_of_wants:
        action_count = total_actions(post.id)
        if page is None: # set page to the last page if not given
            page = math.ceil(float(action_count) / float(ACTIONS_PER_PAGE))
        action_info = actions_with_data(post.id, page)
        ret["actions"] = action_info["actions"]
        ret["rels"].update(dict_by_id(action_info["rels"]))
        ret["posts"].update(dict_by_id(action_info["posts"]))
        ret["action_count"] = action_count
        ret["page"] = int(page)
        ret["comments"] = dict_by_id(action_info["comments"])

    return ret

@blueprint.route('/actions/<int:post_id>')
def actions_endpoint(post_id):
    action_count = total_actions(post_id)
    page = request.args.get('page', math.ceil(float(action_count) / 
                                              float(ACTIONS_PER_PAGE)))
    print("page is %s" % page)
    action_info = actions_with_data(post_id, page)
    return transitify({
        "actions": action_info["actions"], 
        "action_count": action_count, 
        "posts": dict_by_id(action_info["posts"]),
        "rels": dict_by_id(action_info["rels"]),
        "comments": dict_by_id(action_info["comments"]),
        "page": int(page)
    })

@blueprint.route('/links/<int:post_id>')
def links_endpoint(post_id):
    sort_by = request.args.get('sort', 'top')
    page = request.args.get('page', 0)
    rels = child_rel_query(post_id, page=int(page), sort_by=sort_by)
    posts = []
    if rels:
        posts = Post.query.filter(Post.id.in_([r.child_id for r in rels])).all()
    return transitify({
        "posts": dict_by_id([p.writeable for p in posts]), 
        "rels": dict_by_id(
            [r.writeable_with_vote_info(current_user) for r in rels]), 
        "new_rel_ids": [r.id for r in rels]
    })

@blueprint.route('/post-by-id/<int:post_id>')
def render_post(post_id):
    print ("post is %s" % post_id)
    req_data = get_post_data_from_req(request)
    page = req_data.get("page", math.ceil(float(total_actions(post_id)) / 
                                          float(ACTIONS_PER_PAGE)))
    data_only = request.args.get('data-only')
    print ("page is %s" % page)
    app_state = handle_asks(post_id, ["children", "actions"], page=page)
    app_state["user"] = writable_current_user()
    print (app_state)
    if not data_only: 
        return render_template('base.html', debug=SETTINGS["DEBUG"],
                                app_state=transitify(app_state))
    return transitify(app_state)

@blueprint.route('/')
def index():
    app_state = {"user": writable_current_user()}
    return render_post(Post.root_post_id())

@blueprint.route('/post/<post_url>')
def post_page(post_url):
    try:
        p_id = Post.query.filter(Post.url==post_url) \
                         .with_entities(Post.id).one()[0]
    except NoResultFound:
        abort(404)
    return render_post(p_id)

def get_post_data_from_req(request):
    if not request.data:
        return {}
    reader = Reader()
    return reader.read(BytesIO(request.data))

@blueprint.route("/login", methods=["POST"])
def login():
    req_data = get_post_data_from_req(request)
    user = User.login_user(req_data.get("username"), req_data.get("password"))
    if user:
        login_user(user)
        return transitify({"username": user.username, "id": user.id})
    else:
        return transitify({"error": "No user found"})

@blueprint.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    return transitify("Log out successful")

@blueprint.route("/register", methods=["POST"])
def register():
    req_data = get_post_data_from_req(request)
    user = User.register_user(req_data.get("username"), 
                              req_data.get("email"),
                              req_data.get("password"),
                              req_data.get("r-password"))
    if isinstance(user, str):
        return transitify({"error": user})
    login_user(user)
    return transitify({"username": user.username, "id": user.id})

@blueprint.route("/submit-post", methods=["POST"])
def submit_post():
    req_data = get_post_data_from_req(request)
    post = Post.submit_post(current_user,
                     req_data.get("text"),
                     req_data.get("title"))
    if isinstance(post, str):
        return transitify({"error": post, "error_type": "create-post"})

    post_id = req_data.get('parent', Post.root_post_id())
    relation = Relation.link_posts(post_id, 
                                   post, 
                                   current_user)
    if isinstance(relation, str):
        return transitify({"error": relation, "error_type": "link-posts"})

    app_state = {"success": "posted successfully"}
    if req_data.get('current_post') and req_data.get('ask_for'):
        page = req_data.get("page", math.ceil(float(total_actions(post_id)) / 
                                              float(ACTIONS_PER_PAGE)))
        app_state.update(handle_asks(req_data.get('current_post'), 
                                    req_data.get('ask_for'), page))
    return transitify(app_state)

def get_post_id_from_text(s):
    if is_number(s):
        return int(s)
    rt = route_from(s, method="GET")
    if rt[0] == 'views.render_post':
        return rt[1]['post_id']
    elif rt[0] == 'views.post_page':
        try:
            return Post.query.filter(Post.url==rt[1]['post_url']) \
                             .with_entities(Post.id).one()[0]
        except NoResultFound:
            return None
    elif rt[0] == 'views.index':
        return Post.root_post_id()

@blueprint.route("/link-post", methods=["POST"])
def link_post():
    req_data = get_post_data_from_req(request)
    parent_id = req_data.get('parent')
    relation = "Post not found"
    child_id = get_post_id_from_text(req_data.get('child-text'))
    if child_id:
        print("linking post %s" % child_id)
        relation = Relation.link_posts(parent_id, child_id, current_user)
    if isinstance(relation, str):
        return transitify({"error": relation})

    app_state = {"success": "linked successfully"}
    if req_data.get('current_post') and req_data.get('ask_for'):
        page = req_data.get("page", math.ceil(float(total_actions(parent_id)) / 
                                              float(ACTIONS_PER_PAGE)))
        app_state.update(handle_asks(req_data.get('current_post'), 
                                     req_data.get('ask_for'), page))
    return transitify(app_state)

@blueprint.route("/post/<int:post_id>/comment", methods=["POST"])
def submit_comment(post_id):
    req_data = get_post_data_from_req(request)
    comment = Comment.submit_comment(current_user, post_id, req_data.get('body'))
    if isinstance(comment, str):
        return transitify({"error": comment})
    app_state = {"success": "commented successfully"}
    app_state.update(handle_asks(post_id, ["actions"]))
    return transitify(app_state)

@blueprint.route("/vote", methods=["POST"])
def submit_vote():
    req_data = get_post_data_from_req(request)
    vote = Vote.submit_vote(current_user, int(req_data.get('rel_id')), int(req_data.get('value')))
    if isinstance(vote, str):
        return transitify({"error": vote})
    rel = Relation.query.filter(Relation.id==int(req_data.get('rel_id'))).one()
    return transitify({"rel": rel.writeable_with_vote_info()})
