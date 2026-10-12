"""Isolated browser/native fixture with a durable worker and no model calls."""
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend_fixture_server import fixture_parse
from accounts import Accounts
from job_service import Jobs
from worker import run_once, stable_recipes
from application import create_app
import uvicorn


if __name__=='__main__':
    port=int(sys.argv[1]) if len(sys.argv)>1 else 8771
    with tempfile.TemporaryDirectory(prefix='kitchen-native-fixture-') as tmp:
        os.environ['BLOB_ROOT']=str(Path(tmp)/'files')
        path=Path(tmp)/'accounts.db';store=Accounts(path);jobs=Jobs(store);stop=threading.Event()
        def process(job,jobs):
            return stable_recipes(job,fixture_parse(job['payload'],on_event=lambda kind,data:jobs.emit(job,kind,stable_recipes(job,data))))
        def work():
            while not stop.is_set():
                if not run_once(jobs,process):stop.wait(.25)
        thread=threading.Thread(target=work,daemon=True);thread.start()
        print(f'ASGI fixture on 127.0.0.1:{port}; temporary database, no AI usage',flush=True)
        try:uvicorn.run(create_app(path),host='127.0.0.1',port=port,log_level='warning')
        finally:stop.set();thread.join(timeout=2);store.database.close()
