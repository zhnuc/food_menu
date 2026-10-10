"""Isolated browser regression: delayed groups, failed group, old storage."""
import json
from pathlib import Path
import sys
import tempfile
import threading
from http.server import ThreadingHTTPServer
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import pipeline
import server

fixture=json.loads((ROOT/'validation/safe-route-photo-http.json').read_text(encoding='utf-8'))
source={**fixture['media'],'evidence':fixture['evidence'],'warnings':[]}
by_name={r['name']:{key:r[key] for key in ('name','servings','ingredients','steps')} for r in fixture['recipes']}
gate=threading.Event();state={'fail':True}

def request(endpoint,body,*args,**kwargs):
    names=json.loads(body['messages'][1]['content'])['dishNames']
    if names[0]!='辣椒炒肉':gate.wait(timeout=300)
    if names[0]=='椒盐玉米粒' and state['fail']:raise ValueError('测试：最后一组暂时失败')
    return {'choices':[{'message':{'content':json.dumps({'recipes':[by_name[name] for name in names]},ensure_ascii=False)}}]}

class Handler(server.Handler):
    def log_message(self,*args):pass
    def do_GET(self):
        if self.path=='/test/legacy':
            old=[{'id':'legacy-test','name':'旧备份测试菜','servings':2,'targetServings':4,'source':'',
                  'ingredients':[{'name':'番茄','quantity':100,'unit':'克','pending':False,'evidence':'番茄100克'}],
                  'steps':['炒熟'],'evidence':[{'kind':'article','text':'番茄100克炒熟','locator':'旧来源'}],'selected':True}]
            html=('<html><meta charset="utf-8"><script>localStorage.setItem("together-recipes",'+
                  json.dumps(json.dumps(old,ensure_ascii=False))+');location.replace("/");</script></html>')
            raw=html.encode();self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.end_headers();self.wfile.write(raw);return
        return super().do_GET()
    def do_POST(self):
        if self.path=='/test/release':gate.set();return self.respond({'released':True})
        if self.path=='/test/retry':state['fail']=False;gate.set();return self.respond({'retry':True})
        return super().do_POST()

if __name__=='__main__':
    with tempfile.TemporaryDirectory(prefix='frontend-regression-') as tmp,patch('pipeline.RECIPE_CACHE',Path(tmp)),patch.dict(pipeline.os.environ,{'MODEL_API_KEY':'fixture','RECIPE_BATCH_SIZE':'3','RECIPE_WORKERS':'4'}),patch('pipeline.extract_source',return_value=source),patch('pipeline.request_json',side_effect=request):
        print('Browser fixture: http://127.0.0.1:8768/test/legacy',flush=True)
        ThreadingHTTPServer(('127.0.0.1',8768),Handler).serve_forever()
