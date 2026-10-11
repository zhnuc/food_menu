"""Disposable HTTP/browser fixture; never opens the user's account database."""
import json
import sys
import tempfile
from pathlib import Path
from http.server import ThreadingHTTPServer
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import server
from accounts import Accounts


def fixture_parse(payload, on_event=None):
    evidence=[{'id':f'fixture-ev-{i}','kind':'article','text':f'测试菜{i}：鸡蛋1个，炒熟','locator':'测试'} for i in range(1,4)]
    cards=[{'id':f'fixture-card-{i}','name':f'测试菜{i}','servings':1,'targetServings':1,
            'ingredients':[{'name':'鸡蛋','quantity':1,'unit':'个'}],'steps':['炒熟'],
            'evidenceIds':[f'fixture-ev-{i}'],'source':''} for i in range(1,4)]
    result={'recipes':cards,'evidence':evidence,'media':{},'warnings':[],'timings':{}}
    if on_event:
        on_event('source',{'evidence':evidence,'media':{},'warnings':[]})
        for card in cards:on_event('recipes',{'recipes':[card]})
    return result


class Handler(server.Handler):
    def log_message(self,*args):pass


if __name__=='__main__':
    port=int(sys.argv[1]) if len(sys.argv)>1 else 8770
    with tempfile.TemporaryDirectory(prefix='backend-browser-') as tmp, patch('server.parse',side_effect=fixture_parse):
        http=ThreadingHTTPServer(('127.0.0.1',port),Handler)
        http.accounts=Accounts(Path(tmp)/'accounts.db')
        print(f'Isolated backend fixture: http://127.0.0.1:{port}',flush=True)
        try:http.serve_forever()
        finally:http.server_close()
