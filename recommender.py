class HybridRecommender:
    def __init__(self, db_session):
        self.db_session = db_session

    def recommend_for_user(self, user_id, top_n=8):
        # Şimdilik hata vermemesi için boş bir yapı döndürüyoruz
        return {
            "recommendations": [],
            "alpha": 0.5,
            "rmse": 0.0,
            "cf_rmse": 0.0,
            "cbf_rmse": 0.0
        }

    def get_similar_movies(self, movie_id, top_n=4):
        return []

    def get_movie_statistics(self, movie_id):
        return {"avg_rating": 0, "total_ratings": 0}