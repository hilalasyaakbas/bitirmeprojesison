import requests

API_KEY = "b7a102ffd063327aaa162b882ab6f386"
BASE_URL = "https://api.themoviedb.org/3"

def test_fetch(tmdb_id):
    url = f"{BASE_URL}/movie/{tmdb_id}?api_key={API_KEY}&language=tr-TR"
    r = requests.get(url)
    print(f"Status code for {tmdb_id}: {r.status_code}")
    if r.status_code == 200:
        print(f"Poster path: {r.json().get('poster_path')}")
    else:
        print(r.json())

# Let's search for "Untitled Spider-Man Reboot"
search_url = f"{BASE_URL}/search/movie?api_key={API_KEY}&query=Spider-Man"
r = requests.get(search_url)
print("Search results:")
for m in r.json().get('results', [])[:3]:
    print(m['id'], m['title'])
