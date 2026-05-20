import os
import glob

templates_dir = '/Users/hilalasya/bitirmeprojesitemiz/templates'
for filepath in glob.glob(os.path.join(templates_dir, '*.html')):
    with open(filepath, 'r') as f:
        content = f.read()

    # The bad string has escaped backslashes inside Jinja tags
    # Let's replace the entire onerror block with a clean one that doesn't use escaped quotes inside Jinja
    # Old: onerror="this.onerror=null; this.src='{{ url_for(\'static\', filename=\'images/genel.png\') }}';"
    
    # We can just use double quotes for the outer Jinja and single quotes inside, or vice versa.
    # The HTML attribute is double quotes: onerror="..."
    # Inside we have JavaScript: this.src='...'
    # Inside the JS string we have Jinja: {{ url_for('static', filename='images/genel.png') }}
    # So: onerror="this.onerror=null; this.src='{{ url_for('static', filename='images/genel.png') }}';"
    
    content = content.replace(r"url_for(\'static\', filename=\'images/genel.png\')", "url_for('static', filename='images/genel.png')")
    content = content.replace(r"url_for(\"static\", filename=\"images/genel.png\")", "url_for('static', filename='images/genel.png')")
    
    # Just to be safe, replace any literal backslashes that shouldn't be there
    content = content.replace("\\'static\\'", "'static'")
    content = content.replace("\\'images/genel.png\\'", "'images/genel.png'")

    with open(filepath, 'w') as f:
        f.write(content)
print("Syntax fixed")
