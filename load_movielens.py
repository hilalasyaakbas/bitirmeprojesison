import pandas as pd
from app import create_app
from models import db, Movie

def load_data():
    app = create_app()
    
    with app.app_context():
        print("1. Veritabanı tabloları kontrol ediliyor...")
        # create_all zaten app.py içinde çalıştı ama garanti olsun diye ekliyoruz
        db.create_all() 
        
        print("2. Eski veriler temizleniyor (Eğer varsa)...")
        Movie.query.delete()
        db.session.commit()

        print("3. MovieLens CSV dosyaları okunuyor...")
        try:
            # KLASÖR İSMİ SENİN DİZİNİNE GÖRE GÜNCELLENDİ
            movies_df = pd.read_csv('csv-dosyalari/movies.csv')
            links_df = pd.read_csv('csv-dosyalari/links.csv')
        except FileNotFoundError:
            print("HATA: 'csv-dosyalari' klasörü veya CSV dosyaları bulunamadı! Lütfen app.py ile aynı klasörde olduğundan emin ol.")
            return

        # İki tabloyu movieId üzerinden birleştiriyoruz (tmdbId'yi almak için)
        df = pd.merge(movies_df, links_df, on='movieId')
        
        # tmdbId'si boş olan hatalı satırları atlıyoruz
        df = df.dropna(subset=['tmdbId'])

        print(f"4. Toplam {len(df)} film MySQL'e aktarılıyor (Bu işlem 30-40 saniye sürebilir)...")
        
        for index, row in df.iterrows():
            movie = Movie(
                title=row['title'],
                # Türleri listelemek için formata uygun hale getiriyoruz (Action|Adventure -> Action Adventure)
                genres=row['genres'].replace('|', ' '), 
                movielens_id=int(row['movieId']),
                tmdb_id=int(row['tmdbId']),
                # IMDb ID formatını düzeltiyoruz (Örn: 114709 -> tt0114709)
                imdb_id=f"tt{str(int(row['imdbId'])).zfill(7)}" 
            )
            db.session.add(movie)

            # RAM'i yormamak için her 1000 filmde bir veritabanına kalıcı kayıt yapıyoruz
            if index > 0 and index % 1000 == 0:
                db.session.commit()
                print(f"   - {index} film başarıyla eklendi...")

        # Kalan son filmleri de kaydediyoruz
        db.session.commit()
        print("🎉 TEBRİKLER! Tüm MovieLens verileri başarıyla MySQL'e yüklendi.")

if __name__ == '__main__':
    load_data()