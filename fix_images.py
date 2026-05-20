import os
import glob

templates_dir = '/Users/hilalasya/bitirmeprojesitemiz/templates'
for filepath in glob.glob(os.path.join(templates_dir, '*.html')):
    with open(filepath, 'r') as f:
        content = f.read()

    # Fix the missing fallback in similar_movie
    content = content.replace(
        '<img src="{{ similar_movie.poster_url }}" alt="{{ similar_movie.title }} poster">',
        '<img src="{{ similar_movie.poster_url if similar_movie.poster_url and similar_movie.poster_url != \'None\' else url_for(\'static\', filename=\'images/genel.png\') }}" alt="{{ similar_movie.title }} poster" onerror="this.onerror=null; this.src=\'{{ url_for(\\\'static\\\', filename=\\\'images/genel.png\\\') }}\';">'
    )

    # Fix the generic fallback string
    content = content.replace("'/assets/images/genel.png'", "url_for('static', filename='images/genel.png')")
    content = content.replace('"/assets/images/genel.png"', "url_for('static', filename='images/genel.png')")

    # Fix the conditions that don't check for 'None' string
    content = content.replace("if movie.poster_url else", "if movie.poster_url and movie.poster_url != 'None' else")

    with open(filepath, 'w') as f:
        f.write(content)
print("Done fixing images")
