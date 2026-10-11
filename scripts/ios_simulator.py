"""Boot an available iPhone simulator, install, launch and capture the actual app."""
import json
from pathlib import Path
import subprocess
import time

def run(*args):
    return subprocess.check_output(args,text=True).strip()

devices=json.loads(run('xcrun','simctl','list','devices','available','--json'))['devices']
phones=[item for rows in devices.values() for item in rows if item['name'].startswith('iPhone')]
if not phones:raise SystemExit('No installed iPhone simulator runtime')
device=phones[0]['udid']
if phones[0]['state']!='Booted':subprocess.run(['xcrun','simctl','boot',device],check=True)
subprocess.run(['xcrun','simctl','bootstatus',device,'-b'],check=True)
app=Path('ios/DerivedData/Build/Products/Debug-iphonesimulator/App.app')
subprocess.run(['xcrun','simctl','install',device,str(app)],check=True)
result=run('xcrun','simctl','launch',device,'com.yiqichifan.app')
print(result)
time.sleep(12)
Path('output/ios').mkdir(parents=True,exist_ok=True)
subprocess.run(['xcrun','simctl','io',device,'screenshot','output/ios/launched.png'],check=True)
Path('output/ios/simulator.json').write_text(json.dumps({'device':phones[0]['name'],'launch':result}),encoding='utf-8')
