"""Start the recipe backend and its local Antigravity gateway."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from urllib.request import urlopen
import ai

ROOT = Path(__file__).parent
LOGS = ROOT / '.data/logs'


def reachable(url):
    try:
        with urlopen(url, timeout=2) as response:
            return response.status == 200
    except OSError:
        return False


def launch(command, cwd, name, health):
    if reachable(health):
        return None
    LOGS.mkdir(parents=True, exist_ok=True)
    with (LOGS / (name + '.log')).open('a', encoding='utf-8') as log:
        process = subprocess.Popen(command, cwd=cwd, stdout=log, stderr=log,
            env=dict(os.environ, PYTHONIOENCODING='utf-8'),
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    for _ in range(150):
        if reachable(health):
            return process
        if process.poll() is not None:
            raise RuntimeError(name + ' 启动失败，详见 .data/logs')
        time.sleep(.2)
    process.terminate()
    raise RuntimeError(name + ' 启动超时')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--background', action='store_true', help='启动后退出，服务保持运行')
    args = parser.parse_args()
    children = []
    try:
        if ai.settings()[1].startswith('http://127.0.0.1:3000/'):
            node = shutil.which('node')
            if not node:
                raise RuntimeError('Antigravity 网关需要 Node.js')
            process = launch([node, 'src/services/api-server.js'], ROOT / 'services/AIClient2API', 'gateway', 'http://127.0.0.1:3000/health')
            if process: children.append(process)
        port = int(os.getenv('PORT', '8767'))
        address = 'http://127.0.0.1:' + str(port)
        process = launch([sys.executable, str(ROOT / 'server.py')], ROOT, 'recipes', address + '/api/status')
        if process: children.append(process)
        (ROOT / '.data/service-pids.json').write_text(json.dumps([p.pid for p in children]), encoding='utf-8')
        print('一起吃饭：' + address, flush=True)
        if args.background:
            return
        while all(p.poll() is None for p in children):
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    except Exception:
        for process in children:
            if process.poll() is None: process.terminate()
        raise
    finally:
        if not args.background:
            for process in children:
                if process.poll() is None: process.terminate()


if __name__ == '__main__':
    main()
