import os
import requests
import time
from app import create_app
from models import db, Movie

# API Anahtarı (GitHub'a atacağın son aşamada bunu .env içine taşıyacağız, şimdilik test için burada)
API_KEY = "b7a102ffd063327aaa162b882ab6f386"
BASE_URL = "https://api.themoviedb.org/3"

def fetch_movie_details(tmdb_id):
    """TMDb ID kullanarak filmin detaylarını, yönetmenini ve oyuncularını tek seferde çeker."""
    url = f"{BASE_URL}/movie/{tmdb_id}?api_key={API_KEY}&language=tr-TR&append_to_response=credits"
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            details = response.json()
            
            # Yönetmen bilgisini 'crew' içinden ayıkla
            crew = details.get('credits', {}).get('crew', [])
            director = next((member['name'] for member in crew if member['job'] == 'Director'), "Bilinmiyor")
            
            # İlk 5 oyuncuyu alıp aralarına virgül koyarak birleştir
            cast_list = details.get('credits', {}).get('cast', [])[:5]
            cast_names = ", ".join([member['name'] for member in cast_list]) if cast_list else "Oyuncu bilgisi yok"
            
            return {
                "description": details.get('overview', 'Açıklama bulunamadı.'),
                "poster_url": f"https://image.tmdb.org/t/p/w500{details.get('poster_path')}" if details.get('poster_path') else "/assets/images/default-poster.png",
                "director": director,
                "cast": cast_names,
                "duration": details.get('runtime', 0),
                "imdb_rating": details.get('vote_average', 0.0)
            }
    except Exception as e:
        print(f"TMDb ID {tmdb_id} çekilirken API Hatası: {e}")
    return None

def run_enrichment():
    """Veritabanındaki filmleri tarayıp eksik verileri API'den doldurur."""
    app = create_app()
    with app.app_context():
        # Sadece yönetmen bilgisi boş olan filmleri bul (İşlem yarıda kesilirse kaldığı yerden devam edebilsin diye)
        movies_to_update = Movie.query.filter(
    (Movie.director == None) | (Movie.director == '') |
    (Movie.description == None) | (Movie.description == '') |
    (Movie.cast == None) | (Movie.cast == '') |
    (Movie.poster_url == None) | (Movie.poster_url == '')
    ).all()
        total = len(movies_to_update)
        
        if total == 0:
            print("Bütün filmler zaten zenginleştirilmiş! Yapılacak işlem yok.")
            return

        print(f"Toplam {total} filmin metadataları (Özet, Yönetmen, Oyuncu) TMDb'den çekiliyor...")
        print("Uyarı: API rate-limit'e (hız sınırına) takılmamak için bu işlem biraz vakit alacaktır. Arka planda çalışmaya bırakabilirsin.")
        
        for index, movie in enumerate(movies_to_update, 1):
            data = fetch_movie_details(movie.tmdb_id)
            if data:
                movie.description = data['description']
                movie.poster_url = data['poster_url']
                movie.director = data['director']
                movie.cast = data['cast']
                movie.duration = data['duration']
                movie.imdb_rating = data['imdb_rating']
            
            # RAM'i korumak ve verileri güvene almak için her 50 filmde bir kaydet (commit)
            if index % 50 == 0:
                db.session.commit()
                print(f"   🎬 İlerleme: {index} / {total} film güncellendi...")
                time.sleep(1) # TMDb API'sini yormamak ve banlanmamak için 1 saniye bekle
                
        # Kalan küsuratlı filmleri de kaydet
        db.session.commit()
        print("🎉 BÜTÜN FİLMLERİN METADATALARI BAŞARIYLA ZENGİNLEŞTİRİLDİ Ve MYSQL'E YAZILDI!")

if __name__ == '__main__':
    run_enrichment()