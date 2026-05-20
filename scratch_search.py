import requests
API_KEY = "b7a102ffd063327aaa162b882ab6f386"
BASE_URL = "https://api.themoviedb.org/3"
query = "kayıp balık nemo"
url = f"{BASE_URL}/search/movie?api_key={API_KEY}&language=tr-TR&query={query}"
r = requests.get(url)
print(r.json().get('results', [])[0].get('id'))
