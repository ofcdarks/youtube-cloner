"""
Export project from local DB and send to server via API.

Usage: python export_to_server.py <project_id> <server_url> <admin_email> <admin_pass>

Example:
  python export_to_server.py 20260403_220125_pov_atualizado_2 https://cloner.canaisdarks.com.br rudy@ytcloner.com 253031
"""

import sys
import json
import requests

if len(sys.argv) < 5:
    print("Usage: python export_to_server.py <project_id> <server_url> <email> <password>")
    sys.exit(1)

sys.path.insert(0, ".")

PROJECT_ID = sys.argv[1]
SERVER = sys.argv[2].rstrip("/")
EMAIL = sys.argv[3]
PASSWORD = sys.argv[4]

from database import get_project, get_files, get_niches, get_ideas

# 1. Load local data
project = get_project(PROJECT_ID)
if not project:
    print(f"Projeto {PROJECT_ID} nao encontrado no banco local")
    sys.exit(1)

files = get_files(PROJECT_ID)
niches = get_niches(PROJECT_ID)
ideas = get_ideas(PROJECT_ID)

print(f"Projeto: {project['name']}")
print(f"  Arquivos: {len(files)}")
print(f"  Nichos: {len(niches)}")
print(f"  Ideias: {len(ideas)}")

# 2. Login no servidor
print(f"\nConectando em {SERVER}...")
session = requests.Session()
resp = session.post(f"{SERVER}/login", data={"email": EMAIL, "pass": PASSWORD}, allow_redirects=False)

if resp.status_code not in (302, 303):
    print(f"Erro no login: {resp.status_code}")
    sys.exit(1)

cookies = session.cookies
print(f"  Login OK")

# Get CSRF token
import re
page = session.get(f"{SERVER}/").text
csrf_match = re.search(r"CSRF_TOKEN\s*=\s*['\"](.+?)['\"]", page)
csrf = csrf_match.group(1) if csrf_match else ""

# 3. Build payload
payload = {
    "name": project["name"],
    "channel_original": project.get("channel_original", ""),
    "niche_chosen": project.get("niche_chosen", ""),
    "language": project.get("language", "pt-BR"),
    "files": [
        {
            "category": f.get("category", "analise"),
            "label": f.get("label", ""),
            "filename": f.get("filename", ""),
            "content": f.get("content", ""),
        }
        for f in files if f.get("content")
    ],
    "niches": [
        {
            "name": n.get("name", ""),
            "description": n.get("description", ""),
            "rpm_range": n.get("rpm_range", ""),
            "competition": n.get("competition", ""),
            "color": n.get("color", "#888"),
            "chosen": bool(n.get("chosen", 0)),
            "pillars": json.loads(n["pillars"]) if isinstance(n.get("pillars"), str) else n.get("pillars", []),
        }
        for n in niches
    ],
    "ideas": [
        {
            "num": i.get("num", 0),
            "title": i.get("title", ""),
            "hook": i.get("hook", ""),
            "summary": i.get("summary", ""),
            "pillar": i.get("pillar", ""),
            "priority": i.get("priority", "MEDIA"),
        }
        for i in ideas
    ],
}

# 4. Send to server
print(f"\nEnviando projeto ({len(json.dumps(payload))//1024}KB)...")
resp = session.post(
    f"{SERVER}/api/admin/import/full-project",
    json=payload,
    headers={"X-CSRF-Token": csrf, "Content-Type": "application/json"},
)

if resp.status_code == 200:
    data = resp.json()
    if data.get("ok"):
        print(f"\nPROJETO IMPORTADO NO SERVIDOR!")
        print(f"  ID: {data['project_id']}")
        print(f"  Arquivos: {data['files']}")
        print(f"  Nichos: {data['niches']}")
        print(f"  Ideias: {data['ideas']}")
        print(f"\nAcesse: {SERVER}/?project={data['project_id']}")
    else:
        print(f"Erro: {data.get('error', 'desconhecido')}")
else:
    print(f"Erro HTTP {resp.status_code}: {resp.text[:300]}")
