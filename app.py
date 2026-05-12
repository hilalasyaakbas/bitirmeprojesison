import os
from sqlalchemy import or_, text, func # func eklendi
from flask import Flask, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

# Raporundaki API Gateway ve Recommender modülleri
from models import Movie, Rating, User, db
from recommender import HybridRecommender

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

def create_app() -> Flask:
    app = Flask(__name__, static_folder='assets', static_url_path='/assets')
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "filmsage-akbas-2026-secret")
    
    # --- 1. MYSQL BAĞLANTISI ---
    app.config["SQLALCHEMY_DATABASE_URI"] = "mysql+pymysql://root@localhost/movie_sage_db"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)

    with app.app_context():
        db.create_all()

    @app.before_request
    def load_current_user():
        user_id = session.get("user_id")
        g.current_user = User.query.get(user_id) if user_id else None

    @app.context_processor
    def inject_user():
        return {"current_user": g.get("current_user")}

    def require_user():
        if not g.get("current_user"):
            flash("Bu sayfayı görüntülemek için lütfen giriş yapın.", "error")
            return None
        return g.current_user

    @app.route("/")
    def home():
        # MySQL uyumlu sıralama (NULLS LAST yerine otomatik son oylananlar)
        featured = Movie.query.order_by(Movie.imdb_rating.desc(), Movie.year.desc()).limit(12).all()
        return render_template("home.html", featured_movies=featured)

    @app.route("/film-bul")
    def find_movie():
        query = request.args.get("q", "").strip()
        if not query:
            return render_template("search.html", movies=[], query="")

        # --- AKILLI ARAMA MOTORU GÜNCELLEMESİ ---
        # 1. Kullanıcının aramasındaki boşluk ve tireleri temizle
        clean_query = query.replace("-", "").replace(" ", "")

        # 2. Veritabanında hem esnek isim araması yap hem de türlerde ara
        movies = Movie.query.filter(
            or_(
                # Veritabanındaki başlıktaki boşluk ve tireleri yok sayarak eşleştir
                func.replace(func.replace(Movie.title, "-", ""), " ", "").ilike(f"%{clean_query}%"),
                # Türler içinde ara (Action, Sci-Fi vb.)
                Movie.genres.ilike(f"%{query}%")
            )
        ).limit(30).all() # Daha fazla sonuç için limiti 30 yaptık
        
        user_ratings = {}
        if g.get("current_user"):
            user_ratings = {r.movie_id: r.score for r in g.current_user.ratings}
            
        return render_template("search.html", movies=movies, query=query, user_ratings=user_ratings)
    
    @app.route("/rate/<int:movie_id>", methods=["POST"])
    def rate_movie(movie_id):
        user = require_user()
        if not user: return redirect(url_for("kullanici_girisi"))
        
        score = request.form.get("score")
        if score:
            save_rating(user.id, movie_id, float(score))
            flash("Puanınız kaydedildi!", "success")
        
        return redirect(request.referrer or url_for("home"))

    @app.route("/kayit", methods=["GET", "POST"])
    def kullanici_kaydi():
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "")

            if not username or not email or not password:
                flash("Lütfen tüm alanları doldurun.", "error")
            elif User.query.filter((User.username == username) | (User.email == email)).first():
                flash("Bu kullanıcı adı veya e-posta zaten kullanımda.", "error")
            else:
                user = User(username=username, email=email, password_hash=generate_password_hash(password))
                db.session.add(user)
                db.session.commit()
                session["user_id"] = user.id
                return redirect(url_for("on_degerlendirme_puanlamasi"))
        return render_template("auth.html", mode="register")

    @app.route("/giris", methods=["GET", "POST"])
    def kullanici_girisi():
        if request.method == "POST":
            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "")
            user = User.query.filter_by(email=email).first()

            if not user or not check_password_hash(user.password_hash, password):
                flash("Geçersiz e-posta veya şifre.", "error")
            else:
                session["user_id"] = user.id
                return redirect(url_for("on_degerlendirme_puanlamasi"))
        return render_template("auth.html", mode="login")

    @app.route("/cikis")
    def logout():
        session.clear()
        return redirect(url_for("home"))

    @app.route("/on-degerlendirme", methods=["GET", "POST"])
    def on_degerlendirme_puanlamasi():
        user = require_user()
        if not user: return redirect(url_for("kullanici_girisi"))

        selected_genre = request.args.get("genre", "")
        search_query = request.args.get("q", "").strip()

        if request.method == "POST":
            for key, value in request.form.items():
                if not key.startswith("rating_") or not value: continue
                movie_id = int(key.split("_", 1)[1])
                save_rating(user.id, movie_id, float(value))

            if len(user.ratings) >= 5:
                user.is_cold_start_done = True
                db.session.commit()
                return redirect(url_for("kisisel_film_onerileri"))
            
            return redirect(url_for("on_degerlendirme_puanlamasi", genre=selected_genre, q=search_query))

        query = Movie.query
        if selected_genre:
            query = query.filter(Movie.genres.ilike(f"%{selected_genre}%"))
        if search_query:
            query = query.filter(Movie.title.ilike(f"%{search_query}%"))
        
        # Puanlama ekranında popüler filmleri getiriyoruz
        movies_to_rate = query.order_by(Movie.imdb_rating.desc()).limit(21).all()
                              
        genres = ["Action", "Adventure", "Animation", "Comedy", "Drama", "Fantasy", "Sci-Fi", "Romance"]
        
        return render_template("cold_start.html", 
                               movies=movies_to_rate, 
                               genres=genres, 
                               selected_genre=selected_genre, 
                               search_query=search_query,
                               rated_count=len(user.ratings))

    @app.route("/oneriler")
    def kisisel_film_onerileri():
        user = require_user()
        if not user: return redirect(url_for("kullanici_girisi"))
        if not user.is_cold_start_done:
            return redirect(url_for("on_degerlendirme_puanlamasi"))

        recommender = HybridRecommender(db.session)
        result = recommender.recommend_for_user(user.id, top_n=8)
        return render_template("recommendations.html", recommended_movies=result["recommendations"])

    @app.route("/film/<int:movie_id>", methods=["GET", "POST"])
    def movie_detail(movie_id: int):
        user = require_user() 
        if not user: return redirect(url_for("kullanici_girisi"))
        
        movie = Movie.query.get_or_404(movie_id)
        
        stats = {
            "rating_count": len(movie.ratings),
            "average_rating": round(sum([r.score for r in movie.ratings]) / len(movie.ratings), 1) if movie.ratings else 0
        }
        
        imdb_data = {
            "directors": [movie.director] if movie.director else [],
            "actors": movie.cast.split(", ") if movie.cast else []
        }
        
        user_rating_obj = Rating.query.filter_by(user_id=user.id, movie_id=movie_id).first()
        user_rating = user_rating_obj.score if user_rating_obj else None
        
        try:
            recommender = HybridRecommender(db.session)
            similar = recommender.get_similar_movies(movie_id, top_n=4)
        except:
            similar = []

        if request.method == "POST":
            score = request.form.get("score")
            if score:
                save_rating(user.id, movie_id, float(score))
                flash("Puanınız kaydedildi!", "success")
                return redirect(url_for("movie_detail", movie_id=movie_id))
        
        return render_template("movie_detail.html", 
                               movie=movie, 
                               stats=stats, 
                               imdb_data=imdb_data, 
                               user_rating=user_rating,
                               similar_movies=similar)

    return app

def save_rating(user_id: int, movie_id: int, score: float) -> None:
    rating = Rating.query.filter_by(user_id=user_id, movie_id=movie_id).first()
    if rating:
        rating.score = score
    else:
        db.session.add(Rating(user_id=user_id, movie_id=movie_id, score=score))
    db.session.commit()

app = create_app()

if __name__ == "__main__":
    app.run(debug=True)