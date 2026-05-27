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
    
    # --- 1. DİNAMİK VERİTABANI BAĞLANTISI (Lokal & Canlı Uyumlu) ---
    db_uri = os.getenv("DATABASE_URL")
    if db_uri:
        # Aiven veya Render "mysql://" veriyorsa SQLAlchemy için "mysql+pymysql://" yapıyoruz
        if db_uri.startswith("mysql://"):
            db_uri = db_uri.replace("mysql://", "mysql+pymysql://", 1)
            
        # ssl-mode=REQUIRED parametresini temizliyoruz (PyMySQL bu anahtarı doğrudan URL'de tanımaz)
        if "ssl-mode=" in db_uri:
            db_uri = db_uri.split("?ssl-mode=")[0].split("&ssl-mode=")[0]
            
        app.config["SQLALCHEMY_DATABASE_URI"] = db_uri
        
        # Aiven SSL gereksinimi için SSL bağlantı argümanlarını ekliyoruz
        if "aivencloud.com" in db_uri:
            app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
                "connect_args": {
                    "ssl": {}
                }
            }
    else:
        # Lokal MySQL bağlantısı
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

    def ensure_movies_enriched(movies):
        if not movies: return
        from imdb_service import fetch_movie_details
        
        if not isinstance(movies, list):
            movies = [movies]
            
        updated = False
        for movie in movies:
            if not movie: continue
            
            # Eğer afiş yoksa, "None" ise veya eski sabit fotoğraf (/assets/images/...) olarak kaydedilmişse yeniden çek!
            needs_enrichment = (
                not movie.poster_url or 
                movie.poster_url == 'None' or 
                'assets/images' in movie.poster_url or
                not movie.director or 
                movie.director == 'None' or
                not movie.description or 
                movie.description == 'None'
            )
            
            if needs_enrichment:
                data = fetch_movie_details(movie.tmdb_id, title=movie.title, year=movie.year)
                if data:
                    movie.description = data['description']
                    movie.poster_url = data['poster_url']
                    movie.director = data['director']
                    movie.cast = data['cast']
                    movie.duration = data['duration']
                    movie.imdb_rating = data['imdb_rating']
                    if data.get('year'):
                        movie.year = data['year']
                    updated = True
        
        if updated:
            try:
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                print("On the fly enrich DB error:", e)

    @app.route("/")
    def home():
        # Sadece afişi olan, IMDb puanı 7.5 ve üzeri, vizyon yılı >= 1995 olan popüler filmler
        featured = Movie.query.filter(
            Movie.imdb_rating >= 7.5,
            Movie.year >= 1995,
            Movie.poster_url.isnot(None),
            ~Movie.poster_url.like('%default-poster%')
        ).order_by(Movie.imdb_rating.desc(), Movie.year.desc()).limit(12).all()
        
        # Fallback (Eğer henüz zenginleştirme tamamlanmadıysa ve yeterli film dönmezse, genel popülerleri getir)
        if len(featured) < 12:
            featured = Movie.query.filter(
                Movie.poster_url.isnot(None)
            ).order_by(Movie.imdb_rating.desc(), Movie.year.desc()).limit(12).all()
            
        ensure_movies_enriched(featured)
        return render_template("home.html", featured_movies=featured)

    @app.route("/film-bul")
    def find_movie():
        query = request.args.get("q", "").strip()
        if not query:
            return render_template("search.html", movies=[], query="")

        # --- AKILLI VE YAZIM TOLERANSLI ARAMA MOTORU GÜNCELLEMESİ ---
        # 1. Kullanıcının aramasındaki boşluk, tire ve küçük harf normalizasyonunu yap
        clean_query = query.replace("-", "").replace(" ", "").lower()
        
        # Türkçe karakterleri İngilizce karşılıklarına dönüştür
        tr_map = str.maketrans("çğıöşü", "cgiosu")
        eng_query = clean_query.translate(tr_map)
        
        # Çeşitli yazım ve harf hatalı arama kombinasyonlarını üretelim:
        # e -> i, i -> e vokal kaymaları ve c <-> s, ş <-> s vb.
        queries_set = {clean_query, eng_query}
        for q_var in list(queries_set):
            queries_set.add(q_var.replace("c", "s"))
            queries_set.add(q_var.replace("s", "c"))
            queries_set.add(q_var.replace("e", "i"))
            queries_set.add(q_var.replace("i", "e"))
            queries_set.add(q_var.replace("sh", "s"))
            queries_set.add(q_var.replace("ş", "s"))
            queries_set.add(q_var.replace("cinder", "sinder"))
            queries_set.add(q_var.replace("sinder", "cinder"))
            
        queries_list = list(filter(None, queries_set))

        # 2. TMDb API üzerinden çok dilli (Türkçe & Orijinal İngilizce Adı) arama yapıp eşleşen ID'leri al
        from imdb_service import search_tmdb_movies
        tmdb_ids = search_tmdb_movies(query)

        # 3. Kendi veritabanımızda hem normalizasyonlu hem de fuzzy eşleştirme yaparak ara
        conditions = [
            Movie.genres.ilike(f"%{query}%")
        ]
        if tmdb_ids:
            conditions.append(Movie.tmdb_id.in_(tmdb_ids))
            
        for q_var in queries_list:
            conditions.append(func.replace(func.replace(func.lower(Movie.title), "-", ""), " ", "").ilike(f"%{q_var}%"))
            conditions.append(func.replace(func.replace(func.replace(func.lower(Movie.title), "-", ""), " ", ""), "c", "s").ilike(f"%{q_var}%"))
            conditions.append(func.replace(func.replace(func.replace(func.lower(Movie.title), "-", ""), " ", ""), "e", "i").ilike(f"%{q_var}%"))

        movies = Movie.query.filter(or_(*conditions)).limit(30).all()
        
        ensure_movies_enriched(movies)
        
        user_ratings = {}
        if g.get("current_user"):
            user_ratings = {r.movie_id: r.score for r in g.current_user.ratings}
            
        return render_template("search.html", movies=movies, query=query, user_ratings=user_ratings)
    
    @app.route("/rate/<int:movie_id>", methods=["POST"])
    def rate_movie(movie_id):
        user = require_user()
        if not user: 
            if request.is_json:
                return {"status": "error", "message": "Lütfen giriş yapın"}, 401
            return redirect(url_for("kullanici_girisi"))
        
        # AJAX (JSON) veya normal form verisini al
        if request.is_json:
            data = request.get_json() or {}
            score = data.get("score")
        else:
            score = request.form.get("score")
            
        if score:
            save_rating(user.id, movie_id, float(score))
            if request.is_json:
                return {
                    "status": "success", 
                    "message": "Puan başarıyla kaydedildi!", 
                    "score": score,
                    "rated_count": len(user.ratings)
                }
            flash("Puanınız kaydedildi!", "success")
        else:
            if request.is_json:
                return {"status": "error", "message": "Geçersiz puan"}, 400
        
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
        
        # Dinamik Limit ("Daha Fazla Göster" butonu için)
        limit = request.args.get("limit", 21, type=int)

        if request.method == "POST":
            for key, value in request.form.items():
                if not key.startswith("rating_") or not value: continue
                movie_id = int(key.split("_", 1)[1])
                save_rating(user.id, movie_id, float(value))

            if len(user.ratings) >= 5:
                user.is_cold_start_done = True
                db.session.commit()
                return redirect(url_for("kisisel_film_onerileri"))
            
            return redirect(url_for("on_degerlendirme_puanlamasi", genre=selected_genre, q=search_query, limit=limit))

        query = Movie.query
        
        # Oylama ekranında sadece ve sadece vizyon yılı >= 1995, IMDb >= 6.5 olan popüler filmleri tercih et (bilinirlik açısından)
        # Ayrıca afişi olmayan filmleri ele!
        base_filter = Movie.query.filter(
            Movie.year >= 1995,
            Movie.imdb_rating >= 6.5,
            Movie.poster_url.isnot(None),
            ~Movie.poster_url.like('%default-poster%')
        )

        if search_query:
            # Akıllı Arama: Hem yerel veritabanı hem de TMDb eşleşmesi
            # Dil ve yazım toleransı normalizasyonu (Cindirella/Sindirella/Cinderella eşleşmesi için)
            clean_query = search_query.replace("-", "").replace(" ", "").lower()
            
            tr_map = str.maketrans("çğıöşü", "cgiosu")
            eng_query = clean_query.translate(tr_map)
            
            queries_set = {clean_query, eng_query}
            for q_var in list(queries_set):
                queries_set.add(q_var.replace("c", "s"))
                queries_set.add(q_var.replace("s", "c"))
                queries_set.add(q_var.replace("e", "i"))
                queries_set.add(q_var.replace("i", "e"))
                queries_set.add(q_var.replace("sh", "s"))
                queries_set.add(q_var.replace("ş", "s"))
                queries_set.add(q_var.replace("cinder", "sinder"))
                queries_set.add(q_var.replace("sinder", "cinder"))
                
            queries_list = list(filter(None, queries_set))
            
            from imdb_service import search_tmdb_movies
            tmdb_ids = search_tmdb_movies(search_query)
            
            conditions = []
            if tmdb_ids:
                conditions.append(Movie.tmdb_id.in_(tmdb_ids))
                
            for q_var in queries_list:
                conditions.append(func.replace(func.replace(func.lower(Movie.title), "-", ""), " ", "").ilike(f"%{q_var}%"))
                conditions.append(func.replace(func.replace(func.replace(func.lower(Movie.title), "-", ""), " ", ""), "c", "s").ilike(f"%{q_var}%"))
                conditions.append(func.replace(func.replace(func.replace(func.lower(Movie.title), "-", ""), " ", ""), "e", "i").ilike(f"%{q_var}%"))
            
            # Arama yapıldığında, kullanıcının aradığı filmi kesin bulabilmesi için yıl sınırını esnetiyoruz
            movies_to_rate = Movie.query.filter(or_(*conditions)).order_by(Movie.imdb_rating.desc()).limit(limit).all()
        
        elif selected_genre:
            # Kategori seçildiyse: modern ve yüksek puanlı filmleri filtrele
            query = base_filter.filter(Movie.genres.ilike(f"%{selected_genre}%"))
            movies_to_rate = query.order_by(Movie.imdb_rating.desc()).limit(limit).all()
            
            # Fallback (Eğer o kategoride çok az popüler modern film varsa, yıl filtresini 1990'a çekerek tekrar dene)
            if len(movies_to_rate) < 10:
                query = Movie.query.filter(Movie.year >= 1990, Movie.genres.ilike(f"%{selected_genre}%"))
                movies_to_rate = query.order_by(Movie.imdb_rating.desc()).limit(limit).all()
            
        else:
            # HİÇBİR ARAMA/KATEGORİ YOKSA (İLK AÇILIŞ):
            # Kullanıcının kesinlikle bileceği Kült Klasikler ve Popüler Modern Filmlerin MovieLens ID'leri:
            # (Inception, Matrix, Interstellar, Godfather, Pulp Fiction, Dark Knight, Avengers, Forrest Gump, Titanic, Parasite, Joker vb.)
            popular_cult_ids = [
                1, 296, 318, 356, 480, 527, 589, 858, 1196, 2571, 2959, 
                4993, 5952, 7153, 58559, 79132, 109487, 122886, 134130, 89745, 122904,
                27205, 496243, 680, 155, 13, 597 # Eklenen popüler filmler
            ]
            query = Movie.query.filter(Movie.movielens_id.in_(popular_cult_ids))
            movies_to_rate = query.all()
            
        ensure_movies_enriched(movies_to_rate)
                              
        genres = ["Action", "Adventure", "Animation", "Comedy", "Drama", "Fantasy", "Sci-Fi", "Romance"]
        
        user_ratings = {r.movie_id: r.score for r in user.ratings}
        
        return render_template("cold_start.html", 
                               movies=movies_to_rate, 
                               genres=genres, 
                               selected_genre=selected_genre, 
                               search_query=search_query,
                               rated_count=len(user.ratings),
                               user_ratings=user_ratings,
                               limit=limit)

    @app.route("/oneriler")
    def kisisel_film_onerileri():
        user = require_user()
        if not user: return redirect(url_for("kullanici_girisi"))
        if not user.is_cold_start_done:
            return redirect(url_for("on_degerlendirme_puanlamasi"))

        recommender = HybridRecommender(db.session)
        result = recommender.recommend_for_user(user.id, top_n=8)
        ensure_movies_enriched(result["recommendations"])
        return render_template("recommendations.html", recommended_movies=result["recommendations"])

    @app.route("/film/<int:movie_id>", methods=["GET", "POST"])
    def movie_detail(movie_id: int):
        user = require_user() 
        if not user: return redirect(url_for("kullanici_girisi"))
        
        movie = Movie.query.get_or_404(movie_id)
        ensure_movies_enriched([movie])
        
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
            ensure_movies_enriched(similar)
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

    @app.route("/puanlarim", methods=["GET", "POST"])
    def my_ratings():
        user = require_user()
        if not user: return redirect(url_for("kullanici_girisi"))
        
        if request.method == "POST":
            for key, value in request.form.items():
                if not key.startswith("rating_") or not value: continue
                movie_id = int(key.split("_", 1)[1])
                save_rating(user.id, movie_id, float(value))
            flash("Puanlarınız başarıyla güncellendi!", "success")
            return redirect(url_for("my_ratings"))

        rated_movies = []
        movies_to_enrich = []
        for r in user.ratings:
            movie = Movie.query.get(r.movie_id)
            if movie:
                movies_to_enrich.append(movie)
                rated_movies.append({
                    "movie": movie,
                    "score": r.score
                })
        
        ensure_movies_enriched(movies_to_enrich)
            
        return render_template("my_ratings.html", rated_movies=rated_movies)

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