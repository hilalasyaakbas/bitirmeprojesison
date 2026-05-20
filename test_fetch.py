from app import create_app
from models import db, Movie
from imdb_service import fetch_movie_details

app = create_app()
with app.app_context():
    # Find a movie with no poster
    movie = Movie.query.filter((Movie.poster_url == None) | (Movie.poster_url == 'None')).first()
    if movie:
        print(f"Testing fetch for movie: {movie.title} (tmdb_id: {movie.tmdb_id})")
        data = fetch_movie_details(movie.tmdb_id)
        print("Data fetched:")
        print(data)
    else:
        print("No movies without posters found.")
