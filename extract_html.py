import sys
import os

with open('modules/dashboard.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Find DASHBOARD_HTML split
parts = content.split('DASHBOARD_HTML = """')
if len(parts) > 1:
    html_part = parts[1].split('"""')[0]
    os.makedirs('dashboard', exist_ok=True)
    with open('dashboard/index.html', 'w', encoding='utf-8') as f:
        f.write(html_part)
        print('Successfully wrote HTML')

# Update dashboard.py
# Make sure we don't break existing imports
new_dashboard_py = parts[0]
new_dashboard_py = new_dashboard_py.replace('@app.get("/", response_class=HTMLResponse)\nasync def index():\n    return DASHBOARD_HTML', 
"""import os

DASHBOARD_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'dashboard', 'index.html')

@app.get('/', response_class=HTMLResponse)
async def index():
    if os.path.exists(DASHBOARD_PATH):
        with open(DASHBOARD_PATH, 'r', encoding='utf-8') as f:
            return HTMLResponse(f.read())
    return HTMLResponse('Dashboard HTML not found.')
""")

with open('modules/dashboard.py', 'w', encoding='utf-8') as f:
    f.write(new_dashboard_py)
    print('Successfully updated dashboard.py')
