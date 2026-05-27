import pandas as pd
import numpy as np
from surprise import SVD, Dataset, Reader
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import joblib
from models import Movie, Rating


class HybridRecommender:
    def __init__(self, db_session, alpha=0.85):
        self.session = db_session
        self.alpha = alpha  # Default: %85 CF/SVD, %15 CBF/TF-IDF for users with enough rating history.
        self.movies_df = None
        self.tfidf_matrix = None
        self.vectorizer = TfidfVectorizer(stop_words="english")
        self._prepare_data()

    def _clean_text(self, value):
        """Boş veya anlamsız metadata değerlerini TF-IDF içeriğinden temizler."""
        if value is None:
            return ""

        value = str(value).strip()

        invalid_values = {
            "",
            "EMPTY",
            "NULL",
            "NONE",
            "NAN",
            "BILINMIYOR",
            "BİLİNMİYOR",
            "AÇIKLAMA BULUNAMADI.",
            "ACIKLAMA BULUNAMADI.",
            "OYUNCU BİLGİSİ YOK",
            "OYUNCU BILGISI YOK",
        }

        if value.upper() in invalid_values:
            return ""

        return value

    def _get_effective_alpha(self, rating_count):
        """
        Kullanıcının rating sayısına göre dinamik alpha belirler.

        Cold-start aşamasında CBF daha güçlü tutulur.
        Kullanıcıdan daha fazla rating geldikçe CF/SVD ağırlığı artırılır.
        """
        if rating_count <= 10:
            return 0.30  # %30 CF, %70 CBF
        elif rating_count <= 30:
            return 0.55  # %55 CF, %45 CBF
        else:
            return self.alpha  # %85 CF, %15 CBF

    def _prepare_data(self):
        """Veritabanından film metadata bilgisini çeker ve TF-IDF matrisini hazırlar."""
        movies = self.session.query(Movie).order_by(Movie.id).all()

        if not movies:
            return

        movie_data = []

        for movie in movies:
            genres = self._clean_text(movie.genres)
            director = self._clean_text(movie.director)
            cast = self._clean_text(movie.cast)
            description = self._clean_text(movie.description)

            # Genre bilgisini bilinçli olarak birkaç kez ekliyoruz.
            # Bu, cold-start durumda kullanıcının tür tercihinin TF-IDF içinde daha etkili olmasını sağlar.
            # Genre 3 kez, Yönetmen 2 kez eklenerek TF-IDF ağırlıkları artırıldı.
            content = (
                f"{genres} {genres} {genres} "
                f"{director} {director} "
                f"{cast} "
                f"{description}"
            )

            movie_data.append({
                "id": movie.id,
                "content": content
            })

        self.movies_df = pd.DataFrame(movie_data)

        if self.movies_df.empty:
            return

        self.tfidf_matrix = self.vectorizer.fit_transform(self.movies_df["content"])

    def recommend_for_user(self, user_id, top_n=8):
        """SVD tabanlı CF ve TF-IDF tabanlı CBF skorlarını birleştirerek hibrit öneri üretir."""
        ratings = self.session.query(Rating).all()

        if not ratings or self.movies_df is None or self.tfidf_matrix is None:
            fallback_movies = (
                self.session.query(Movie)
                .order_by(Movie.imdb_rating.desc())
                .limit(top_n)
                .all()
            )
            return {
                "recommendations": fallback_movies,
                "alpha": None
            }

        df_ratings = pd.DataFrame([
            {
                "user_id": rating.user_id,
                "movie_id": rating.movie_id,
                "score": rating.score
            }
            for rating in ratings
        ])

        # 1. Collaborative Filtering - SVD
                # 1. Collaborative Filtering - SVD (Kayıtlı Hazır Model Okunuyor)
        svd_model = joblib.load("svd_model.pkl")

        # 2. Content-Based Filtering - TF-IDF user profile
        user_ratings = self.session.query(Rating).filter_by(user_id=user_id).all()
        user_movie_ids = [rating.movie_id for rating in user_ratings]

        # 1995 ve sonrası modern filmleri VEYA eski dev kült klasikleri (IMDb >= 8.2) filtrele. Afişi eksik olanları önerme!
        allowed_movies = self.session.query(Movie.id).filter(
            ((Movie.year >= 1995) | ((Movie.year < 1995) & (Movie.imdb_rating >= 8.2))),
            Movie.poster_url.isnot(None),
            ~Movie.poster_url.like('%default-poster%')
        ).all()
        allowed_ids = {m[0] for m in allowed_movies}

        effective_alpha = self._get_effective_alpha(len(user_ratings))

        # 1-10 rating ölçeğinde 7 ve üzeri beğenilmiş kabul edilir.
        liked_movies = [
            rating for rating in user_ratings
            if rating.score >= 7.0
        ]

        if liked_movies:
            liked_movie_ids = [rating.movie_id for rating in liked_movies]
            liked_indices = self.movies_df[
                self.movies_df["id"].isin(liked_movie_ids)
            ].index

            if len(liked_indices) > 0:
                user_profile = self.tfidf_matrix[liked_indices].mean(axis=0)
                user_profile = np.asarray(user_profile)
                cbf_scores = cosine_similarity(user_profile, self.tfidf_matrix).flatten()
            else:
                cbf_scores = np.zeros(len(self.movies_df))
        else:
            cbf_scores = np.zeros(len(self.movies_df))

        # 3. Weighted Hybrid Scoring
        # Performans için IMDb puanlarını tek bir sorguyla önbelleğe alıyoruz
        movie_imdb_ratings = {
            m[0]: (m[1] if m[1] else 0.0)
            for m in self.session.query(Movie.id, Movie.imdb_rating).filter(Movie.id.in_(allowed_ids)).all()
        }

        hybrid_recommendations = []

        for idx, row in self.movies_df.iterrows():
            movie_id = int(row["id"])

            if movie_id in user_movie_ids:
                continue

            # Kaliteli ve modern/kült film filtresinden geçir
            if movie_id not in allowed_ids:
                continue

            # SVD tahmini 1-10 aralığındadır; 0-1 aralığına normalize edilir.
            cf_score = svd_model.predict(user_id, movie_id).est / 10

            # TF-IDF cosine similarity skoru doğal olarak 0-1 aralığındadır.
            cbf_score = cbf_scores[idx]

            # Filmin IMDb puanını 0-1 arasına normalize ederek 3. ağırlık olarak ekliyoruz
            imdb_rating = movie_imdb_ratings.get(movie_id, 0.0)
            imdb_score = imdb_rating / 10.0

            # Kişisel zevk hibrit bazı (%60)
            hybrid_base = (effective_alpha * cf_score) + ((1 - effective_alpha) * cbf_score)

            # Nihai hibrit skor: %60 kişiselleştirilmiş zevk tahmini, %40 global kalite/popülerlik (IMDb)
            final_score = (0.6 * hybrid_base) + (0.4 * imdb_score)

            hybrid_recommendations.append((movie_id, final_score))

        hybrid_recommendations.sort(key=lambda item: item[1], reverse=True)

        top_ids = [movie_id for movie_id, _ in hybrid_recommendations[:top_n]]

        final_movies = (
            self.session.query(Movie)
            .filter(Movie.id.in_(top_ids))
            .all()
        )

        ordered_movies = sorted(final_movies, key=lambda movie: top_ids.index(movie.id))

        return {
            "recommendations": ordered_movies,
            "alpha": effective_alpha
        }

    def get_similar_movies(self, movie_id, top_n=4):
        """TF-IDF cosine similarity kullanarak benzer filmleri döndürür."""
        if self.movies_df is None or self.tfidf_matrix is None:
            return []

        movie_indices = self.movies_df[self.movies_df["id"] == movie_id].index

        if len(movie_indices) == 0:
            return []

        idx = movie_indices[0]

        sim_scores = cosine_similarity(
            self.tfidf_matrix[idx],
            self.tfidf_matrix
        ).flatten()

        related_indices = sim_scores.argsort()[-(top_n + 1):-1][::-1]
        related_ids = self.movies_df.iloc[related_indices]["id"].tolist()

        return (
            self.session.query(Movie)
            .filter(Movie.id.in_(related_ids))
            .all()
        )