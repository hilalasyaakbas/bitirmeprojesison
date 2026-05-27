import os
import requests
import time
import re
from app import create_app
from models import db, Movie

# API Anahtarı (GitHub'a atacağın son aşamada bunu .env içine taşıyacağız, şimdilik test için burada)
API_KEY = "b7a102ffd063327aaa162b882ab6f386"
BASE_URL = "https://api.themoviedb.org/3"

def normalize_title(title):
    if not title: return ""
    clean = re.sub(r'\(\d{4}\)', '', title).strip()
    match = re.match(r'^(.*),\s*(The|A|An)$', clean, flags=re.IGNORECASE)
    if match:
        clean = f"{match.group(2)} {match.group(1)}"
    return clean.strip()

def is_title_match(original_title, tmdb_title):
    t1 = normalize_title(original_title).lower()
    t2 = normalize_title(tmdb_title).lower()
    if not t1 or not t2: return False
    if t1 in t2 or t2 in t1: return True
    
    # Türkçe harf normalizasyonu ve ses uyumu (c <-> s, ş <-> s, ç <-> c, e <-> i vb.)
    tr_map = str.maketrans("çğıöşü", "cgiosu")
    t1_tr = t1.translate(tr_map).replace("c", "s").replace("e", "i")
    t2_tr = t2.translate(tr_map).replace("c", "s").replace("e", "i")
    if t1_tr in t2_tr or t2_tr in t1_tr: return True
    
    w1 = set(w for w in t1.split() if len(w) > 2)
    w2 = set(w for w in t2.split() if len(w) > 2)
    return len(w1.intersection(w2)) > 0


def _parse_tmdb_response(details, is_tv=False):
    crew = details.get('credits', {}).get('crew', [])
    if is_tv:
        created_by = details.get('created_by', [])
        if created_by:
            director = created_by[0]['name']
        else:
            director = next((member['name'] for member in crew if member.get('job') in ['Director', 'Executive Producer']), "Bilinmiyor")
        duration = details.get('episode_run_time', [0])[0] if details.get('episode_run_time') else 0
    else:
        director = next((member['name'] for member in crew if member.get('job') == 'Director'), "Bilinmiyor")
        duration = details.get('runtime', 0)
        
    cast_list = details.get('credits', {}).get('cast', [])[:5]
    cast_names = ", ".join([member['name'] for member in cast_list]) if cast_list else "Oyuncu bilgisi yok"
    
    poster_path = details.get('poster_path')
    
    # Vizyon tarihi yılı ayıklama
    release_date = details.get('release_date') or details.get('first_air_date', '')
    year = None
    if release_date and len(release_date) >= 4:
        try:
            year = int(release_date[:4])
        except:
            pass
            
    return {
        "title": details.get('title') or details.get('name', ''),
        "description": details.get('overview', 'Açıklama bulunamadı.') or 'Açıklama bulunamadı.',
        "poster_url": f"https://image.tmdb.org/t/p/w500{poster_path}" if poster_path else "/assets/images/default-poster.png",
        "director": director,
        "cast": cast_names,
        "duration": duration,
        "imdb_rating": details.get('vote_average', 0.0),
        "year": year
    }

def fetch_movie_details(tmdb_id, title=None, year=None):
    """5 Kademeli Akıllı Oto-Kurtarma Sistemi ile Afiş ve Metadata Çeker"""
    try:
        url = f"{BASE_URL}/movie/{tmdb_id}?api_key={API_KEY}&language=tr-TR&append_to_response=credits"
        response = requests.get(url, timeout=10)
        
        if response.status_code == 200:
            res_json = response.json()
            parsed = _parse_tmdb_response(res_json, is_tv=False)
            orig_title = res_json.get('original_title') or res_json.get('original_name', '')
            if title and not (is_title_match(title, parsed['title']) or is_title_match(title, orig_title)):
                response.status_code = 404 # Force fallback
            else:
                return parsed

        if response.status_code == 404 and title:
            clean_title = normalize_title(title)
            search_queries = [(clean_title, year), (clean_title, None)]

            for q_title, q_year in search_queries:
                if not q_title: continue
                
                search_url = f"{BASE_URL}/search/multi?api_key={API_KEY}&language=tr-TR&query={q_title}"
                if q_year: search_url += f"&year={q_year}"
                
                search_resp = requests.get(search_url, timeout=10)
                if search_resp.status_code == 200:
                    results = search_resp.json().get('results', [])
                    for r in results:
                        if r.get('media_type') in ['movie', 'tv']:
                            new_id = r['id']
                            is_tv = (r['media_type'] == 'tv')
                            final_url = f"{BASE_URL}/{'tv' if is_tv else 'movie'}/{new_id}?api_key={API_KEY}&language=tr-TR&append_to_response=credits"
                            
                            final_resp = requests.get(final_url, timeout=10)
                            if final_resp.status_code == 200:
                                f_json = final_resp.json()
                                parsed = _parse_tmdb_response(f_json, is_tv=is_tv)
                                orig_title_fallback = f_json.get('original_title') or f_json.get('original_name', '')
                                if (is_title_match(title, parsed['title']) or 
                                    is_title_match(q_title, parsed['title']) or 
                                    is_title_match(title, orig_title_fallback)):
                                    return parsed
    except Exception as e:
        print(f"TMDb API Hatası (ID: {tmdb_id}, Title: {title}): {e}")
    return None

def search_tmdb_movies(query):
    """Kullanıcının girdiği kelimeyi TMDb üzerinde (tr-TR) aratır ve eşleşen tmdb_id listesini döndürür."""
    if not query: return []
    url = f"{BASE_URL}/search/movie?api_key={API_KEY}&language=tr-TR&query={query}"
    try:
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            results = response.json().get('results', [])
            return [movie['id'] for movie in results[:15]]
    except Exception as e:
        print(f"TMDb Arama Hatası: {e}")
    return []

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