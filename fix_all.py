import os
import glob

templates_dir = '/Users/hilalasya/bitirmeprojesitemiz/templates'
fallback_url = 'https://placehold.co/400x600/141423/00d4ff?text=Afis+Bekleniyor'

for filepath in glob.glob(os.path.join(templates_dir, '*.html')):
    with open(filepath, 'r') as f:
        content = f.read()

    # Replace the broken url_for for genel.png with placehold.co
    content = content.replace("url_for('static', filename='images/genel.png')", f"'{fallback_url}'")
    
    # In base.html, revert logo.svg to hardcoded absolute path to avoid any url_for issues
    content = content.replace("url_for('static', filename='images/logo.svg')", "'/assets/images/logo.svg'")
    
    # Same for css and js just in case
    content = content.replace("url_for('static', filename='css/style.css')", "'/assets/css/style.css'")
    content = content.replace("url_for('static', filename='js/script.js')", "'/assets/js/script.js'")

    with open(filepath, 'w') as f:
        f.write(content)

print("All templates updated with placehold.co and absolute static paths.")
