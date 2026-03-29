from datetime import datetime

from flask_sqlalchemy import SQLAlchemy
db = SQLAlchemy()


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    is_cold_start_done = db.Column(db.Boolean, default=False)
    ratings = db.relationship("Rating", backref="user", lazy=True, cascade="all, delete-orphan")


class Movie(db.Model):
    __tablename__ = "movies"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    year = db.Column(db.Integer)
    quality = db.Column(db.String(20))
    duration = db.Column(db.Integer)
    poster_url = db.Column(db.String(255))
    description = db.Column(db.Text)
    genres = db.Column(db.String(200))
    imdb_rating = db.Column(db.Float)
    imdb_url = db.Column(db.String(255))
    ratings = db.relationship("Rating", backref="movie", lazy=True, cascade="all, delete-orphan")
    director = db.Column(db.String(100)) 
    cast = db.Column(db.String(500))     #

class Rating(db.Model):
    __tablename__ = "ratings"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    movie_id = db.Column(db.Integer, db.ForeignKey("movies.id"), nullable=False)
    score = db.Column(db.Float, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
