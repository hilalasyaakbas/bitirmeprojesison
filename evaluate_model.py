import numpy as np
import pandas as pd

from surprise import SVD, Dataset, Reader
from surprise.model_selection import train_test_split
from surprise.accuracy import rmse

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.metrics import mean_squared_error

from app import create_app
from models import db, Movie, Rating


def build_movie_content_dataframe():
    movies = Movie.query.all()

    movie_data = []
    for movie in movies:
        content = (
            f"{movie.genres or ''} "
            f"{movie.director or ''} "
            f"{movie.cast or ''} "
            f"{movie.description or ''}"
        )

        movie_data.append({
            "movie_id": movie.id,
            "content": content
        })

    return pd.DataFrame(movie_data)


def calculate_cbf_predictions(train_df, test_df, movies_df):
    vectorizer = TfidfVectorizer(stop_words="english")
    tfidf_matrix = vectorizer.fit_transform(movies_df["content"])

    movie_index_map = {
        movie_id: index
        for index, movie_id in enumerate(movies_df["movie_id"].tolist())
    }

    cbf_predictions = []

    for _, test_row in test_df.iterrows():
        user_id = test_row["user_id"]
        target_movie_id = test_row["movie_id"]

        user_train_ratings = train_df[train_df["user_id"] == user_id]
        liked_movies = user_train_ratings[user_train_ratings["score"] >= 7.0]

        if liked_movies.empty or target_movie_id not in movie_index_map:
            cbf_predictions.append(5.5)
            continue

        liked_indices = [
            movie_index_map[movie_id]
            for movie_id in liked_movies["movie_id"].tolist()
            if movie_id in movie_index_map
        ]

        if not liked_indices:
            cbf_predictions.append(5.5)
            continue

        target_index = movie_index_map[target_movie_id]

        user_profile = tfidf_matrix[liked_indices].mean(axis=0)
        user_profile = np.asarray(user_profile)

        cbf_score_0_1 = cosine_similarity(user_profile, tfidf_matrix[target_index]).flatten()[0]

        # CBF cosine score 0-1 aralığındadır.
        # Rating ölçeği 1-10 olduğu için 1-10 aralığına map ediyoruz.
        cbf_score_1_10 = 1 + (cbf_score_0_1 * 9)

        cbf_predictions.append(cbf_score_1_10)

    return np.array(cbf_predictions)


def evaluate():
    app = create_app()

    with app.app_context():
        ratings = Rating.query.all()

        if not ratings:
            print("HATA: Rating tablosunda veri yok. Önce load_ratings.py çalıştırılmalı.")
            return

        ratings_df = pd.DataFrame([
            {
                "user_id": rating.user_id,
                "movie_id": rating.movie_id,
                "score": rating.score
            }
            for rating in ratings
        ])

        movies_df = build_movie_content_dataframe()

        if movies_df.empty:
            print("HATA: Movie tablosunda veri yok. Önce loadmovelens.py ve imdb_service.py çalıştırılmalı.")
            return

        print("Toplam rating sayısı:", len(ratings_df))
        print("Toplam film sayısı:", len(movies_df))
        print()

        # Surprise SVD için veri hazırlanır.
        reader = Reader(rating_scale=(1, 10))
        data = Dataset.load_from_df(
            ratings_df[["user_id", "movie_id", "score"]],
            reader
        )

        trainset, testset = train_test_split(data, test_size=0.05, random_state=42)

        svd_model = SVD(random_state=42)
        svd_model.fit(trainset)

        svd_predictions = svd_model.test(testset)
        svd_rmse = rmse(svd_predictions, verbose=False)

        # testset Surprise formatında tuple döner: (user_id, movie_id, true_rating)
        test_df = pd.DataFrame([
            {
                "user_id": user_id,
                "movie_id": movie_id,
                "score": true_rating
            }
            for user_id, movie_id, true_rating in testset
        ])

        # trainset'i pandas dataframe olarak yeniden oluşturuyoruz.
        train_df = ratings_df.merge(
            test_df[["user_id", "movie_id"]],
            on=["user_id", "movie_id"],
            how="left",
            indicator=True
        )

        train_df = train_df[train_df["_merge"] == "left_only"].drop(columns=["_merge"])

        true_scores = test_df["score"].to_numpy()

        cf_scores = np.array([
            prediction.est
            for prediction in svd_predictions
        ])

        cbf_scores = calculate_cbf_predictions(train_df, test_df, movies_df)
        cbf_rmse = np.sqrt(mean_squared_error(true_scores, cbf_scores))

        print("MODEL RMSE RESULTS")
        print("------------------")
        print(f"SVD / Collaborative Filtering RMSE: {svd_rmse:.4f}")
        print(f"TF-IDF / Content-Based Filtering RMSE: {cbf_rmse:.4f}")
        print()

        print("HYBRID ALPHA SEARCH")
        print("-------------------")

        best_alpha = None
        best_rmse = float("inf")

        alpha_values = [round(x, 2) for x in np.arange(0.0, 1.01, 0.05)]

        for alpha in alpha_values:
            hybrid_scores = (alpha * cf_scores) + ((1 - alpha) * cbf_scores)
            hybrid_rmse = np.sqrt(mean_squared_error(true_scores, hybrid_scores))

            print(f"alpha={alpha:.2f} -> Hybrid RMSE: {hybrid_rmse:.4f}")

            if hybrid_rmse < best_rmse:
                best_rmse = hybrid_rmse
                best_alpha = alpha

        print()
        print("BEST RESULT")
        print("-----------")
        print(f"Best alpha: {best_alpha}")
        print(f"Best Hybrid RMSE: {best_rmse:.4f}")

        print()
        print("Öneri:")
        print(f"recommend.py içindeki default alpha değerini {best_alpha} yapabilirsin.")


if __name__ == "__main__":
    evaluate()