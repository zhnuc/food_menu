"""Generate the static offline inventory after changes and before app sync."""
import hashlib
import json
import re
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
web=ROOT/'web'
files=sorted(path for path in web.rglob('*') if path.is_file() and path.name not in ('offline-assets.json','offline-worker.js') and path.suffix in ('.js','.css','.html','.json','.png','.svg','.woff2'))
digest=hashlib.sha256()
for path in files:digest.update(path.relative_to(web).as_posix().encode());digest.update(path.read_bytes())
(web/'offline-assets.json').write_text(json.dumps({'version':digest.hexdigest()[:16],'files':['/'+path.relative_to(web).as_posix() for path in files]},ensure_ascii=False,indent=2),encoding='utf-8')
worker=web/'offline-worker.js'
worker.write_text(re.sub(r"const CACHE='together-shell-[^']+';",f"const CACHE='together-shell-{digest.hexdigest()[:16]}';",worker.read_text(encoding='utf-8')),encoding='utf-8')
print(f'Offline inventory: {len(files)} files')
