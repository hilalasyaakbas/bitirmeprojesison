from app import create_app
from models import db, Movie

app = create_app()
with app.app_context():
    total = Movie.query.count()
    missing_poster = Movie.query.filter((Movie.poster_url == None) | (Movie.poster_url == '')).count()
    has_none_string = Movie.query.filter(Movie.cast == 'None').count()
    print(f"Total movies: {total}")
    print(f"Missing poster: {missing_poster}")
    print(f"Cast is literal 'None': {has_none_string}")
