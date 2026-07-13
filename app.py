import os
from flask import Flask, render_template, request, redirect, url_for, flash, abort
from flask_sqlalchemy import SQLAlchemy
from flask_login import (
    LoginManager, UserMixin, login_user, logout_user,
    current_user, login_required
)
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
from functools import wraps

# --- Инициализация ---
app = Flask(__name__)
app.config['SECRET_KEY'] = 'super-secret-key-change-me'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///blog.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# --- Модели БД ---
# Таблица для связи подписок (многие-ко-многим)
followers = db.Table('followers',
    db.Column('follower_id', db.Integer, db.ForeignKey('user.id')),
    db.Column('followed_id', db.Integer, db.ForeignKey('user.id'))
)

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(200))
    posts = db.relationship('Post', backref='author', lazy='dynamic')
    followed = db.relationship(
        'User', secondary=followers,
        primaryjoin=(followers.c.follower_id == id),
        secondaryjoin=(followers.c.followed_id == id),
        backref=db.backref('followers', lazy='dynamic'), lazy='dynamic'
    )

    def follow(self, user):
        if not self.is_following(user):
            self.followed.append(user)

    def unfollow(self, user):
        if self.is_following(user):
            self.followed.remove(user)

    def is_following(self, user):
        return self.followed.filter(followers.c.followed_id == user.id).count() > 0

# Таблица тегов (многие-ко-многим с постами)
post_tags = db.Table('post_tags',
    db.Column('post_id', db.Integer, db.ForeignKey('post.id')),
    db.Column('tag_id', db.Integer, db.ForeignKey('tag.id'))
)

class Tag(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)

class Post(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    body = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, index=True, default=datetime.utcnow)
    is_private = db.Column(db.Boolean, default=False)  # Скрытый пост
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    tags = db.relationship('Tag', secondary=post_tags, backref=db.backref('posts', lazy='dynamic'))

class Comment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    body = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'))
    user = db.relationship('User')

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --- Декоратор для проверки доступа к скрытому посту ---
def check_post_access(func):
    @wraps(func)
    def wrapper(post_id, *args, **kwargs):
        post = Post.query.get_or_404(post_id)
        if post.is_private:
            if not current_user.is_authenticated:
                flash('Этот пост скрыт. Войдите или запросите доступ.')
                return redirect(url_for('login'))
            if post.author != current_user:
                flash('Это приватный пост. Доступ только у автора (по запросу).')
                return redirect(url_for('index'))
        return func(post_id, *args, **kwargs)
    return wrapper

# --- Роуты ---
@app.route('/')
def index():
    # Публичные посты (или посты от подписок, если пользователь залогинен)
    page = request.args.get('page', 1, type=int)
    if current_user.is_authenticated:
        # Посты от пользователей, на которых подписан + свои
        followed_ids = [u.id for u in current_user.followed] + [current_user.id]
        posts = Post.query.filter(
            Post.user_id.in_(followed_ids),
            Post.is_private == False
        ).order_by(Post.timestamp.desc()).paginate(page=page, per_page=5)
    else:
        posts = Post.query.filter_by(is_private=False).order_by(Post.timestamp.desc()).paginate(page=page, per_page=5)
    return render_template('index.html', posts=posts)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        if User.query.filter_by(username=username).first():
            flash('Пользователь уже существует')
            return redirect(url_for('register'))
        user = User(username=username, email=email)
        user.password_hash = generate_password_hash(password)
        db.session.add(user)
        db.session.commit()
        login_user(user)
        return redirect(url_for('index'))
    return render_template('register.html')








@app.route('/profile/<int:user_id>')
def view_profile(user_id):
    profile_user = User.query.get_or_404(user_id)
    # Показываем только публичные посты (или скрытые, если это владелец профиля)
    if current_user == profile_user:
        posts = Post.query.filter_by(user_id=user_id).order_by(Post.timestamp.desc()).all()
    else:
        posts = Post.query.filter_by(user_id=user_id, is_private=False).order_by(Post.timestamp.desc()).all()
    return render_template('profile.html', profile_user=profile_user, posts=posts)










@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form['username']).first()
        if user and check_password_hash(user.password_hash, request.form['password']):
            login_user(user)
            return redirect(url_for('index'))
        flash('Неверные данные')
    return render_template('login.html')

@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/create', methods=['GET', 'POST'])
@login_required
def create_post():
    if request.method == 'POST':
        title = request.form['title']
        body = request.form['body']
        is_private = 'is_private' in request.form
        tag_string = request.form['tags']  # строка через запятую
        post = Post(title=title, body=body, author=current_user, is_private=is_private)
        if tag_string:
            tag_names = [name.strip().lower() for name in tag_string.split(',') if name.strip()]
            for name in tag_names:
                tag = Tag.query.filter_by(name=name).first()
                if not tag:
                    tag = Tag(name=name)
                post.tags.append(tag)
        db.session.add(post)
        db.session.commit()
        return redirect(url_for('index'))
    return render_template('create_post.html')

@app.route('/edit/<int:post_id>', methods=['GET', 'POST'])
@login_required
def edit_post(post_id):
    post = Post.query.get_or_404(post_id)
    if post.author != current_user:
        abort(403)
    if request.method == 'POST':
        post.title = request.form['title']
        post.body = request.form['body']
        post.is_private = 'is_private' in request.form
        # Обновление тегов
        post.tags.clear()
        tag_string = request.form['tags']
        if tag_string:
            tag_names = [name.strip().lower() for name in tag_string.split(',') if name.strip()]
            for name in tag_names:
                tag = Tag.query.filter_by(name=name).first()
                if not tag:
                    tag = Tag(name=name)
                post.tags.append(tag)
        db.session.commit()
        return redirect(url_for('view_post', post_id=post.id))
    return render_template('create_post.html', post=post, edit_mode=True)

@app.route('/delete/<int:post_id>', methods=['POST'])
@login_required
def delete_post(post_id):
    post = Post.query.get_or_404(post_id)
    if post.author != current_user:
        abort(403)
    db.session.delete(post)
    db.session.commit()
    return redirect(url_for('index'))

@app.route('/post/<int:post_id>')
@check_post_access
def view_post(post_id):
    post = Post.query.get_or_404(post_id)
    return render_template('post_detail.html', post=post)

@app.route('/post/<int:post_id>/comment', methods=['POST'])
@login_required
def add_comment(post_id):
    post = Post.query.get_or_404(post_id)
    if post.is_private and post.author != current_user:
        abort(403)
    body = request.form['body']
    comment = Comment(body=body, user_id=current_user.id, post_id=post_id)
    db.session.add(comment)
    db.session.commit()
    return redirect(url_for('view_post', post_id=post_id))






@app.errorhandler(404)
def not_found_error(error):
    return render_template('404.html'), 404

@app.errorhandler(403)
def forbidden_error(error):
    flash('У вас нет доступа к этому ресурсу.')
    return redirect(url_for('index'))






@app.route('/users')
def list_users():
    users = User.query.all()
    return render_template('users.html', users=users)

@app.route('/follow/<int:user_id>')
@login_required
def follow(user_id):
    user_to_follow = User.query.get_or_404(user_id)
    if user_to_follow == current_user:
        flash('Нельзя подписаться на себя')
        return redirect(url_for('list_users'))
    current_user.follow(user_to_follow)
    db.session.commit()
    return redirect(url_for('list_users'))

@app.route('/unfollow/<int:user_id>')
@login_required
def unfollow(user_id):
    user_to_unfollow = User.query.get_or_404(user_id)
    current_user.unfollow(user_to_unfollow)
    db.session.commit()
    return redirect(url_for('list_users'))

@app.route('/feed')
@login_required
def feed():
    # Лента подписок
    followed_ids = [u.id for u in current_user.followed]
    posts = Post.query.filter(Post.user_id.in_(followed_ids), Post.is_private == False).order_by(Post.timestamp.desc()).all()
    return render_template('index.html', posts=posts)

# Фильтрация по тегам
@app.route('/tag/<string:tag_name>')
def posts_by_tag(tag_name):
    tag = Tag.query.filter_by(name=tag_name).first_or_404()
    posts = tag.posts.filter_by(is_private=False).order_by(Post.timestamp.desc()).all()
    return render_template('index.html', posts=posts, tag_filter=tag_name)

# Инициализация БД
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)