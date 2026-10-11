import copy
import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, build_opener, HTTPCookieProcessor
from accounts import Accounts, AccountError
from account_http import AccountRoutes


def snapshot():
    return {'state': {'version': 1, 'spaces': [], 'stocks': [], 'records': [], 'operations': [],
                      'meal': {'id': 'meal-one', 'status': 'draft', 'selections': [], 'dishes': [], 'needs': []}},
            'recipeData': {'version': 2, 'recipes': [], 'evidence': {}}}


class AccountTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Accounts(Path(self.tmp.name)/'accounts.db')
        self.payload = {'login': 'alice', 'password': 'test-pass-123', 'nickname': '小禾', 'snapshot': snapshot()}
        self.token = self.store.register(self.payload, 'test')

    def tearDown(self):
        self.tmp.cleanup()

    def test_password_session_and_logout(self):
        with self.store.connect() as db:
            encoded = db.execute('SELECT password FROM users').fetchone()[0]
            token = db.execute('SELECT token FROM sessions').fetchone()[0]
        self.assertNotIn('test-pass-123', encoded)
        self.assertNotEqual(token, self.token)
        with self.assertRaises(AccountError): self.store.login({**self.payload, 'password': 'wrong'}, 'test')
        logged = self.store.login(self.payload, 'test')
        self.assertNotEqual(logged, self.token)
        self.assertEqual(self.store.current(logged)['user']['nickname'], '小禾')
        self.store.logout(logged)
        with self.assertRaises(AccountError): self.store.current(logged)
        self.assertEqual(self.store.current(self.token)['user']['login'], 'alice')

    def test_independent_accounts_join_shared_family_and_revision_conflict(self):
        bob = self.store.register({**self.payload, 'login': 'bob', 'nickname': '小满'}, 'test')
        alice = self.store.current(self.token)
        self.assertNotEqual(self.store.current(bob)['household']['id'], alice['household']['id'])
        joined = self.store.join(bob, {'code': alice['household']['invite'].lower()})
        self.assertEqual(len(joined['members']), 2)
        self.assertNotEqual(joined['user']['id'], alice['user']['id'])
        self.store.command(self.token, {'id':'add-eggs-1','revision':1,'role':'chef','kind':'stock.add',
                           'payload':{'name':'鸡蛋','quantity':3,'unit':'个','space':None,'zone':0}})
        self.assertEqual(self.store.current(bob)['snapshot']['state']['stocks'][0]['quantity'], 3)
        with self.assertRaises(AccountError) as error:
            self.store.command(bob, {'id':'add-eggs-2','revision':1,'role':'chef','kind':'stock.add',
                               'payload':{'name':'鸡蛋','quantity':1,'unit':'个','space':None,'zone':0}})
        self.assertEqual(error.exception.status, 409)
        self.assertEqual(self.store.current(self.token)['revision'], 2)

    def test_profile_validation_and_locked_menu_cannot_be_rewritten(self):
        updated = self.store.profile(self.token, {'nickname':'阿满', 'avatar':''})
        self.assertEqual(updated['user']['nickname'], '阿满')
        for avatar in ('https://example.com/a.png', 'data:image/svg+xml;base64,AAAA', 'data:image/png;base64,AAAA'):
            with self.assertRaises(AccountError): self.store.profile(self.token, {'nickname':'阿满','avatar':avatar})
        update = snapshot();update['state']['meal']['status']='locked'
        with self.assertRaises(AccountError) as error: self.store.save(self.token, {'revision':1,'snapshot':update})
        self.assertEqual(error.exception.status, 410)
        self.assertEqual(self.store.current(self.token)['snapshot']['state']['meal']['status'], 'draft')

    def test_bad_registration_and_snapshot_do_not_create_records(self):
        for payload in ({**self.payload,'login':'a'}, {**self.payload,'password':'tiny'}, {**self.payload,'nickname':' '}):
            with self.assertRaises(AccountError): self.store.register(payload, 'test')
        invalid = snapshot();invalid['state']['stocks']=[{'id':'x','name':'x','quantity':-1,'unit':'克','zone':0,'space':None}]
        with self.assertRaises(AccountError): self.store.save(self.token, {'revision':1,'snapshot':invalid})
        self.assertEqual(self.store.current(self.token)['revision'], 1)
        self.store.logout(self.token)
        with self.assertRaises(AccountError): self.store.save(self.token, {'revision':1,'snapshot':snapshot()})

    def test_http_cookie_origin_and_unauthenticated_access(self):
        class Handler(AccountRoutes, SimpleHTTPRequestHandler):
            def do_GET(self): self.account_route('GET')
            def do_POST(self): self.account_route('POST')
            def log_message(self, *args): pass
        server = ThreadingHTTPServer(('127.0.0.1',0), Handler);server.accounts=self.store
        worker=threading.Thread(target=server.serve_forever, daemon=True);worker.start()
        url='http://127.0.0.1:'+str(server.server_port)
        jar=CookieJar();http=build_opener(HTTPCookieProcessor(jar))
        def post(path, data, origin=url):
            return http.open(Request(url+path,data=json.dumps(data).encode(),headers={'Content-Type':'application/json','Origin':origin}))
        try:
            self.assertIsNone(json.load(http.open(url+'/api/account/session'))['user'])
            with self.assertRaises(HTTPError) as error: post('/api/household/save', {'revision':1,'snapshot':snapshot()})
            self.assertEqual(error.exception.code,401)
            response=post('/api/account/login',self.payload)
            self.assertIn('HttpOnly',response.headers['Set-Cookie']);self.assertIn('SameSite=Strict',response.headers['Set-Cookie'])
            self.assertEqual(json.load(response)['user']['login'],'alice')
            command={'id':'http-add-eggs','revision':1,'role':'chef','kind':'stock.add',
                     'payload':{'name':'鸡蛋','quantity':3,'unit':'个','space':None,'zone':0}}
            updated=json.load(post('/api/household/commands',command))
            self.assertEqual(updated['snapshot']['state']['stocks'][0]['quantity'],3)
            replay=json.load(post('/api/household/commands',command))
            self.assertTrue(replay['duplicate']);self.assertEqual(replay['revision'],updated['revision'])
            with self.assertRaises(HTTPError) as error:post('/api/household/save',{'revision':2,'snapshot':snapshot()})
            self.assertEqual(error.exception.code,410)
            with self.assertRaises(HTTPError) as error: post('/api/account/profile',{'nickname':'changed'},'https://evil.invalid')
            self.assertEqual(error.exception.code,403)
            post('/api/account/logout',{}).close()
            self.assertIsNone(json.load(http.open(url+'/api/account/session'))['user'])
            self.assertEqual(self.store.current(self.token)['user']['nickname'],'小禾')
        finally:
            server.shutdown();server.server_close();worker.join()


if __name__ == '__main__': unittest.main()
