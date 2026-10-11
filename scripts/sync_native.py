"""Copy public UI into a native bundle; credentials and server files stay out."""
import json
import os
import shutil
from pathlib import Path
from urllib.parse import urlsplit
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
api=os.getenv('APP_API_URL','http://10.0.2.2:8767').rstrip('/')
url=urlsplit(api)
if url.scheme not in ('https','http') or not url.hostname or url.username or url.password or url.query or url.fragment or url.path:
    raise SystemExit('APP_API_URL 必须为不含凭据的服务器根地址')
if os.getenv('APP_RELEASE')=='1' and url.scheme!='https':
    raise SystemExit('发布版需要 HTTPS APP_API_URL')
subprocess.run([sys.executable,str(ROOT/'scripts/build_offline.py')],check=True,cwd=ROOT)
destination=ROOT/'.data/native-web'
destination.mkdir(parents=True,exist_ok=True)
shutil.copytree(ROOT/'web',destination,dirs_exist_ok=True)
(destination/'native-config.js').write_text('window.APP_API_URL='+json.dumps(api)+';\nwindow.APP_ALLOW_HTTP='+('false' if os.getenv('APP_RELEASE')=='1' else 'true')+';\n',encoding='utf-8')
index=destination/'index.html'
index.write_text(index.read_text(encoding='utf-8').replace('<script defer src="ids.js','<script src="native-config.js"></script>\n  <script defer src="native-bridge.js"></script>\n  <script defer src="ids.js'),encoding='utf-8')
print('Native public assets ready; no server secrets copied')
