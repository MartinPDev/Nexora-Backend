from pathlib import Path
import re

path = Path("main.py")
text = path.read_text()

Path("main_before_js_extract.py").write_text(text)

# Find the dashboard_ui function area only
start = text.index('def dashboard_ui(username: str):')
end = text.index('app.include_router(auth_router', start)
dashboard_block = text[start:end]

# Find the LAST inline <script>...</script> inside dashboard_ui
scripts = list(re.finditer(r'<script>\s*(.*?)\s*</script>', dashboard_block, flags=re.S))

if not scripts:
    raise SystemExit("No dashboard script found.")

script_match = scripts[-1]
script_body = script_match.group(1)

# Convert Python f-string JS braces to normal JS braces
script_body = script_body.replace('{{', '{').replace('}}', '}')

# Replace Python-injected username with static JS username variable
script_body = script_body.replace('{username}', '${USERNAME}')

# Add username constant at top of app.js
app_js = 'const USERNAME = window.DASHBOARD_USERNAME;\n\n' + script_body.strip() + '\n'

Path("static/app.js").write_text(app_js)

# Remove the inline dashboard script only, keep external app.js
new_dashboard_block = (
    dashboard_block[:script_match.start()]
    + '<script src="/static/app.js"></script>'
    + dashboard_block[script_match.end():]
)

new_text = text[:start] + new_dashboard_block + text[end:]

# Avoid duplicate external script lines
new_text = new_text.replace(
    '<script src="/static/app.js"></script>\n<script src="/static/app.js"></script>',
    '<script src="/static/app.js"></script>'
)

path.write_text(new_text)

print("Dashboard JavaScript moved to static/app.js")
print("Backup saved as main_before_js_extract.py")
