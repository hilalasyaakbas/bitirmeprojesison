import os
import pandas as pd

from app import create_app
from models import db, Movie, Rating, User


def load_ratings():
    app = create_app()

    with app.app_context():
        print("1. Veritabanı tabloları kontrol ediliyor...")
        db.create_all()

        print("2. MovieLens ratings.csv dosyası okunuyor...")
        ratings_path = os.path.join("csv-dosyalari", "ratings.csv")

        try:
            ratings_df = pd.read_csv(ratings_path)
        except FileNotFoundError:
            print("HATA: csv-dosyalari/ratings.csv bulunamadı.")
            return

        print("3. MovieLens movieId -> local Movie.id eşleşmesi hazırlanıyor...")
        movies = Movie.query.all()
        movielens_to_local_id = {
            movie.movielens_id: movie.id
            for movie in movies
            if movie.movielens_id is not None
        }

        print("4. MovieLens kullanıcıları için sistem kullanıcıları oluşturuluyor...")
        unique_user_ids = ratings_df["userId"].unique()

        existing_users = User.query.filter(User.username.like("movielens_user_%")).all()
        existing_user_map = {
            int(user.username.replace("movielens_user_", "")): user.id
            for user in existing_users
            if user.username.replace("movielens_user_", "").isdigit()
        }

        for movielens_user_id in unique_user_ids:
            if int(movielens_user_id) not in existing_user_map:
                user = User(
                    username=f"movielens_user_{int(movielens_user_id)}",
                    email=f"movielens_user_{int(movielens_user_id)}@movielens.local",
                    password_hash="imported_movielens_user",
                    is_cold_start_done=True
                )
                db.session.add(user)

        db.session.commit()

        all_movielens_users = User.query.filter(User.username.like("movielens_user_%")).all()
        user_id_map = {
            int(user.username.replace("movielens_user_", "")): user.id
            for user in all_movielens_users
            if user.username.replace("movielens_user_", "").isdigit()
        }

        print("5. Eski MovieLens rating kayıtları temizleniyor...")
        movielens_local_user_ids = list(user_id_map.values())

        if movielens_local_user_ids:
            Rating.query.filter(Rating.user_id.in_(movielens_local_user_ids)).delete(synchronize_session=False)
            db.session.commit()

        print("6. Rating verileri MySQL'e aktarılıyor...")

        inserted_count = 0
        skipped_count = 0

        for index, row in ratings_df.iterrows():
            movielens_user_id = int(row["userId"])
            movielens_movie_id = int(row["movieId"])
            original_score = float(row["rating"])

            local_user_id = user_id_map.get(movielens_user_id)
            local_movie_id = movielens_to_local_id.get(movielens_movie_id)

            if not local_user_id or not local_movie_id:
                skipped_count += 1
                continue

            # MovieLens rating ölçeği genelde 0.5-5 arasıdır.
            # Sistem 1-10 kullandığı için 2 ile çarpıyoruz.
            normalized_score = original_score * 2

            rating = Rating(
                user_id=local_user_id,
                movie_id=local_movie_id,
                score=normalized_score
            )
            db.session.add(rating)
            inserted_count += 1

            if inserted_count % 5000 == 0:
                db.session.commit()
                print(f"   - {inserted_count} rating aktarıldı...")

        db.session.commit()

        print("Tamamlandı.")
        print(f"Aktarılan rating sayısı: {inserted_count}")
        print(f"Atlanan rating sayısı: {skipped_count}")


if __name__ == "__main__":
    load_ratings()