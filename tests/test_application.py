"""ASGI transport checks use real cookie sessions and transactional storage."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from accounts import Accounts
from application import create_app
from test_kitchen_service import bundle


class ApplicationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.env=patch.dict('os.environ',{'BLOB_ROOT':str(Path(self.tmp.name)/'files')})
        self.env.start();self.addCleanup(self.env.stop)
        self.hash=patch.object(Accounts,'password_hash',staticmethod(lambda password,salt=None:'0'*32+':test'))
        self.hash.start();self.addCleanup(self.hash.stop)
        self.client=TestClient(create_app(Path(self.tmp.name)/'accounts.db'))
        self.client.__enter__();self.addCleanup(lambda:self.client.__exit__(None,None,None))

    def register(self):
        response=self.client.post('/api/account/register',json={'login':'test-user','nickname':'测试','password':'password123','snapshot':bundle()})
        self.assertEqual(response.status_code,200);self.assertIn('HttpOnly',response.headers['set-cookie'])
        return response.json()

    def test_cookie_auth_commands_and_legacy_rejection(self):
        self.assertEqual(self.client.get('/api/health').json()['ok'],True)
        data=self.register()
        command={'id':'test-command-001','revision':data['revision'],'role':'chef','kind':'stock.add','payload':{'name':'鸡蛋','quantity':2,'unit':'个','space':None}}
        first=self.client.post('/api/household/commands',json=command)
        self.assertEqual(first.status_code,200)
        second=self.client.post('/api/household/commands',json=command)
        self.assertTrue(second.json()['duplicate']);self.assertEqual(second.json()['revision'],first.json()['revision'])
        self.assertEqual(self.client.post('/api/household/save',json={}).status_code,410)
        self.assertEqual(self.client.post('/api/household/commands',json=command,headers={'Origin':'https://evil.invalid'}).status_code,403)
        self.client.post('/api/account/logout',json={})
        self.assertIsNone(self.client.get('/api/account/session').json()['user'])
        self.assertEqual(self.client.post('/api/household/commands',json=command).status_code,401)

    def test_parse_requires_login_and_stream_remains_compatible(self):
        self.assertEqual(self.client.post('/api/parse',json={'share':'test'}).status_code,401)
        self.register()
        def fake(body,on_event=None):
            on_event('recipes',{'recipes':[]})
            return {'recipes':[],'warnings':[],'timings':{}}
        with patch('application.parse',side_effect=fake),patch.dict('os.environ',{'ALLOW_INLINE_PARSE':'1'}):
            response=self.client.post('/api/parse',json={'share':'test'},headers={'Accept':'application/x-ndjson'})
        self.assertEqual(response.status_code,200);self.assertIn('"type": "done"',response.text)

    def test_invalid_content_and_static_assets(self):
        self.assertEqual(self.client.post('/api/account/login',content='bad').status_code,415)
        self.assertEqual(self.client.post('/api/account/login',json=[]).status_code,400)
        self.assertEqual(self.client.get('/').status_code,200)
        self.assertIn('一起吃饭',self.client.get('/').text)

    def test_private_image_upload_profile_and_job_transport(self):
        import io
        from PIL import Image
        output=io.BytesIO();Image.new('RGB',(12,12),'red').save(output,format='PNG');raw=output.getvalue()
        self.assertEqual(self.client.post('/api/files',content=raw).status_code,401)
        self.register()
        response=self.client.post('/api/files?purpose=avatar',content=raw);self.assertEqual(response.status_code,200)
        url=response.json()['url'];self.assertEqual(self.client.get(url).status_code,200)
        updated=self.client.post('/api/account/profile',json={'nickname':'新昵称','avatar':url})
        self.assertEqual(updated.json()['user']['avatar'],url)
        self.assertEqual(self.client.post('/api/files',content=b'not an image').status_code,400)
        job=self.client.post('/api/jobs',json={'requestId':'request-test-001','kind':'text','input':{'prompt':'做一道家常菜'}})
        self.assertEqual(job.status_code,200);identity=job.json()['id']
        self.assertEqual(self.client.get('/api/jobs/'+identity).json()['status'],'queued')
        self.assertEqual(len(self.client.get('/api/jobs').json()['jobs']),1)
        self.assertEqual(self.client.post('/api/jobs/'+identity+'/cancel',json={}).json()['status'],'cancelled')
        self.client.post('/api/account/logout',json={})
        self.assertEqual(self.client.get(url).status_code,401)
        self.client.post('/api/account/register',json={'login':'other-user','nickname':'外人','password':'password123','snapshot':bundle()})
        self.assertEqual(self.client.get(url).status_code,404)
        self.assertEqual(self.client.get('/api/jobs/'+identity).status_code,404)


if __name__=='__main__':unittest.main()
