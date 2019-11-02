import datetime as dt
import pytz
import string
import random

from localsettings import SETTINGS
from flask import Flask
from flask_bcrypt import Bcrypt
from flask_login import UserMixin
from sqlalchemy.sql import func
# from sqlalchemy import and_
import re
from app import db, login_manager
from slugify import slugify

bcrypt = Bcrypt()

def doc_or_doc_id(docname, value, dict_to_update=None):
    dict_to_update = dict_to_update or {}
    if isinstance(value, int):
        docname += "_id"
    dict_to_update[docname] = value
    return dict_to_update 


class SurrogatePK(object):
    """A mixin that adds a surrogate integer 'primary key' column named
    ``id`` to any declarative-mapped class.
    """
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, primary_key=True)

class CRUDMixin(object):
    """Mixin that adds convenience methods for CRUD (create, read, update, delete)
    operations.
    """

    def set_attr_or_id(self, attrname, **kw):
        if kw[attrname]:
            setattr(self, attrname, kw[attrname])
        elif kw[attrname + "_id"]:
            setattr(self, attrname + "_id", kw[attrname + "_id"])
        else: 
            raise Exception("Missing %s information" % attrname)
        return self

    @classmethod
    def create(cls, **kwargs):
        """Create a new record and save it the database."""
        instance = cls(**kwargs)
        return instance.save()

    def update(self, commit=True, **kwargs):
        """Update specific fields of a record."""
        for attr, value in kwargs.iteritems():
            setattr(self, attr, value)
        return commit and self.save() or self

    def save(self, commit=True):
        """Save the record."""
        db.session.add(self)
        if commit:
            db.session.commit()
        return self

    def delete(self, commit=True):
        """Remove the record from the database."""
        db.session.delete(self)
        return commit and db.session.commit()

class Model(CRUDMixin, db.Model, SurrogatePK):
    __abstract__ = True

class User(Model, UserMixin):
    __tablename__ = 'users'
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(128), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=dt.datetime.utcnow)
    active = db.Column(db.Boolean(), default=False)
    is_admin = db.Column(db.Boolean(), default=False)

    def __init__(self, username, email, password=None, **kwargs):
        db.Model.__init__(self, username=username, email=email, **kwargs)
        if password:
            self.set_password(password)
        else:
            self.password = None

    def set_password(self, password):
        self.password = bcrypt.generate_password_hash(password)

    def check_password(self, value):
        return bcrypt.check_password_hash(self.password, value)

    @classmethod
    def get_admin_user(cls):
        return cls.query.filter_by(username=SETTINGS["admin_username"]).first()

    @classmethod
    def admin_user_id(cls):
        return 1

    @classmethod
    def login_user(cls, username, password):
        user = cls.query.filter_by(username=username).first()
        if user and user.check_password(password):
            return user
        else:
            return None

    @classmethod
    def register_user(cls, username, email, password, r_password):
        if re.search(r'[\s]', username):
            return "username can't contain spaces"
        if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
            return "You must use a valid email address"
        if password != r_password:
            return "Your passwords don't match"
        if len(password) < 7:
            return "Your password must be atleast 7 characters"
        user = cls.query.filter_by(username=username).first() 
        if user:
            return "That username is taken"
        user = cls.query.filter_by(email=email).first()
        if user:
            return "That email address is already in use"

        return cls.create(username=username, email=email, password=password)

    @property
    def writeable(self):
        return {"username": self.username, "id": self.id}

    def __repr__(self):
        return '<User({username!r})>'.format(username=self.username)


def make_url(title, body=''):
    url = slugify(title or body[:140])
    i = 1
    while True:
        if Post.query.filter(Post.url==url).count() == 0:
            break
        if i > 1000:
            print("reached 1000 loops for post with title, body: %s" % (title, body))
            raise
        i += 1
        url = url.split(".")[0] + "." + str(i)
    return url

class Post(Model):
    __tablename__ = 'posts'
    title = db.Column(db.String(140))
    body = db.Column(db.Text)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    user = db.relationship('User', backref=db.backref('posts', lazy='dynamic'))
    time_posted = db.Column(db.DateTime, nullable=False, default=dt.datetime.utcnow)
    time_edited = db.Column(db.DateTime, nullable= True, default= None)
    url = db.Column(db.String(160), unique=True)

    def get_child_relations(self, limit=8, ids_only=False):
        if not ids_only:
            return Relation.query.filter(Relation.parent_id == self.id).limit(limit)
        return Relation.query.with_entities(Relation.id) \
                             .filter(Relation.parent_id==self.id).limit(limit)

    def get_children(self, limit=8):
        child_ids = [rel.child_id for rel in self.get_child_relations(limit=limit)]
        return Post.query.filter(Post.id.in_(child_ids)).all()

    def get_parent_relations(self, limit=8):
        return Relation.query.filter(Relation.child_id==self.id).limit(limit)

    def get_parents(self, limit=8):
        parent_ids = [rel.parent_id for rel in self.get_parent_relations(limit=limit)]
        return Post.query.filter(Post.id.in_(parent_ids)).all()

    def get_comments(self, limit=10):
        return Comment.query.filter(Comment.post_id==self.id).limit(limit)

    def __init__(self, title, body, user=None, user_id=None, time_posted=None):
        self.title = title
        self.body = body
        if time_posted is None:
            time_posted = dt.datetime.utcnow()
        self.time_posted = time_posted
        self.set_attr_or_id("user", user=user, user_id=user_id)
        self.url = make_url(title, body)

    @classmethod
    def get_root_post(cls):
        return cls.query.first()

    @classmethod
    def root_post_id(cls):
        return 1

    @classmethod
    def submit_post(cls, user, text, title=None):
        if not (user and text):
            return "you need to include text to submit a post"
        if title and len(title) > 140:
            return "your title must be less than 140 characters long"
        return cls.create(title=title, body=text, user=user)

    def edit_post(self, title, body):
        if (title and len(title) > 140):
            return "your title must be less than 140 characters long"
        self.title = title
        self.body = body
        self.time_edited = dt.datetime.utcnow()


    @property
    def writeable(self):
        attrs = ("id", "title", "body", "user_id", "time_posted", "url")
        ret_dict = {k: self.__dict__.get(k, None) for k in attrs}
        ret_dict["time_posted"] = pytz.utc.localize(ret_dict["time_posted"])
        return ret_dict

    def __repr__(self):
        return '<Post %r>' % self.title



class Relation(Model):
    __tablename__ = 'relations'
    parent_id = db.Column(db.Integer, db.ForeignKey('posts.id'))
    parent = db.relationship('Post', foreign_keys=[parent_id],
        backref=db.backref('parent_relations', lazy='dynamic'))
    child_id = db.Column(db.Integer, db.ForeignKey('posts.id'))
    child = db.relationship('Post', foreign_keys=[child_id],
        backref=db.backref('child_relations', lazy='dynamic'))
    linked_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    linked_by = db.relationship('User', backref=db.backref('links', lazy='dynamic'))
    time_linked = db.Column(db.DateTime, nullable=False, default=dt.datetime.utcnow)


    def __init__(self, parent=None, parent_id=None, child=None, child_id=None, 
                 linked_by=None, linked_by_id=None, time_linked=None):
        self.set_attr_or_id("parent", parent=parent, parent_id=parent_id)
        self.set_attr_or_id("child", child=child, child_id=child_id)
        self.set_attr_or_id("linked_by", linked_by=linked_by, linked_by_id=linked_by_id)
        if time_linked is None:
            time_linked = dt.datetime.utcnow()
        self.time_linked = time_linked

    @classmethod
    def link_posts(cls, parent, child, user):
        if not (parent and child and user):
            return "missing data"

        kw = {}
        kw = doc_or_doc_id("parent", parent, kw)
        kw = doc_or_doc_id("child", child, kw)
        kw = doc_or_doc_id("linked_by", user, kw)
        return cls.create(**kw)

    def get_votes(self, limit=None):
        if limit is None:
            return Vote.query.filter(Vote.rel_id==self.id)
        return Vote.query.filter(Vote.rel_id==self.id).limit(limit)

    @property
    def votecount(self):
        vote_sum = self.get_votes().with_entities(func.sum(Vote.value)).first()[0]
        return int(vote_sum) if vote_sum is not None else 0

    @property
    def writeable(self):
        attrs = ("id", "parent_id", "child_id", "linked_by", "time_linked", "votecount")
        ret_dict = {k: getattr(self, k) for k in attrs}
        ret_dict["time_linked"] = pytz.utc.localize(ret_dict["time_linked"])
        ret_dict["linked_by"] = ret_dict["linked_by"].writeable
        return ret_dict

    def writeable_with_vote_info(self, user=None):
        vote_value = 0
        if user is None:
            return dict(list(self.writeable.items()) + [("user_vote_value", vote_value)])
        user_id = user if isinstance(user, int) else user.id
        vote = Vote.query.filter((Vote.rel_id==self.id) & (Vote.user_id==user_id)).first()
        if vote:
            vote_value = int(vote.value)
        return dict(list(self.writeable.items()) + [("user_vote_value", vote_value)])

    def __repr__(self):
        return '<Relation %r>' % self.id

class Comment(Model):
    __tablename__ = 'comments'
    body = db.Column(db.Text)
    post_id = db.Column(db.Integer, db.ForeignKey('posts.id'))
    post = db.relationship('Post', backref=db.backref('comments', lazy='dynamic'))
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    user = db.relationship('User', backref=db.backref('comments', lazy='dynamic'))
    time_posted = db.Column(db.DateTime, nullable=False, default=dt.datetime.utcnow)

    def __init__(self, body, post=None, post_id=None, 
                 user=None, user_id=None, time_posted=None):
        self.body = body
        self.set_attr_or_id("post", post=post, post_id=post_id)
        self.set_attr_or_id("user", user=user, user_id=user_id)
        if time_posted is None:
            time_posted = dt.datetime.utcnow()
        self.time_posted = time_posted

    @classmethod
    def submit_comment(cls, user, post, body):
        if not (user and post and body):
            return "missing data"

        kw = {"body": body}
        kw = doc_or_doc_id("user", user, kw)
        kw = doc_or_doc_id("post", post, kw)
        return cls.create(**kw)

    @property
    def writeable(self):
        attrs = ("id", "body", "post_id", "user", "time_posted")
        ret_dict = {k: getattr(self, k, None) for k in attrs}
        ret_dict["time_posted"] = pytz.utc.localize(ret_dict["time_posted"])
        ret_dict["user"] = ret_dict["user"].writeable
        return ret_dict

    def __repr__(self):
        return '<Comment %r>' % self.body

class Vote(CRUDMixin, db.Model):
    __tablename__ = 'votes'
    rel_id = db.Column(db.Integer, db.ForeignKey('relations.id'), primary_key=True)
    rel = db.relationship('Relation', backref=db.backref('votes', lazy='dynamic'))
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), primary_key=True)
    user = db.relationship('User', backref=db.backref('votes', lazy='dynamic'))
    value = db.Column(db.Integer)

    def __init__(self, value=1, rel=None, rel_id=None, user=None, user_id=None):
        self.set_attr_or_id("rel", rel=rel, rel_id=rel_id)
        self.set_attr_or_id("user", user=user, user_id=user_id)
        self.value = value

    @classmethod
    def submit_vote(cls, user, rel, value=True):
        if not (user and rel):
            return "missing data"

        user_id = user if isinstance(user, int) else user.id
        rel_id = rel if isinstance(rel, int) else rel.id
        value = 1 if value == 1 else -1
        vote = cls.query.filter((Vote.user_id==user_id) & (Vote.rel_id==rel_id)).first()
        if vote:
            if vote.value == value:
                return vote.delete()
            return vote.update(value=value)
        return cls.create(user_id=user_id, rel_id=rel_id, value=value)

    def __repr__(self):
        return '<Vote user:%r rel:%r value:%s>' % (self.user_id, self.rel_id, self.value)


@login_manager.user_loader
def load_user(userid):
    return User.query.get(userid)

def setup_db(drop_tables_first=False):
    if drop_tables_first:
        db.drop_all()
    db.create_all()
    # create admin user
    admin_user = User.create(username=SETTINGS["admin_username"],
                             password=SETTINGS["admin_password"],
                             email=SETTINGS["admin_email"])
    # create root post
    Post.create(title="Welcome to Openthink!",
                body="Browse these posts or submit your own!",
                user=admin_user)
