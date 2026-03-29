import requests

# TMDb API Anahtarı
API_KEY = "b7a102ffd063327aaa162b882ab6f386"
BASE_URL = "https://api.themoviedb.org/3"

def fetch_imdb_movie_data(title):
    # 1. Filmi TMDb üzerinden ara
    search_url = f"{BASE_URL}/search/movie?api_key={API_KEY}&query={title}&language=tr-TR"
    try:
        response = requests.get(search_url).json()
        
        if response.get('results'):
            movie_data = response['results'][0] # En popüler ilk sonucu al
            movie_id = movie_data['id']
            
            # 2. Filmin detaylarını (süre, oyuncular ve ekip) çek
            # 'append_to_response=credits' ekleyerek yönetmen ve oyuncu bilgilerini de istiyoruz
            detail_url = f"{BASE_URL}/movie/{movie_id}?api_key={API_KEY}&language=tr-TR&append_to_response=credits"
            details = requests.get(detail_url).json()
            
            # Yönetmen bilgisini 'crew' içinden ayıklıyoruz
            crew = details.get('credits', {}).get('crew', [])
            director = next((member['name'] for member in crew if member['job'] == 'Director'), "Bilinmiyor")
            
            # İlk 5 oyuncuyu alıp aralarına virgül koyarak birleştiriyoruz
            cast_list = details.get('credits', {}).get('cast', [])[:5]
            cast_names = ", ".join([member['name'] for member in cast_list]) if cast_list else "Oyuncu bilgisi yok"
            
            return {
                "title": details.get('title'),
                "year": int(details.get('release_date', '0000')[:4]) if details.get('release_date') else 2024,
                "description": details.get('overview', 'Açıklama bulunamadı.'),
                "poster_url": f"https://image.tmdb.org/t/p/w500{details.get('poster_path')}" if details.get('poster_path') else "/assets/images/default-poster.png",
                "imdb_rating": details.get('vote_average', 0.0),
                "genres": " ".join([g['name'] for g in details.get('genres', [])]),
                "duration": details.get('runtime', 0),
                "imdb_url": f"https://www.themoviedb.org/movie/{movie_id}",
                "director": director,  # Yeni eklenen yönetmen verisi
                "cast": cast_names      # Yeni eklenen oyuncu verisi
            }
    except Exception as e:
        print(f"API Hatası: {e}")
    return None