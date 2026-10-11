import io
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from accounts import Accounts,AccountError
from job_service import Jobs
from worker import run_once,stable_recipes
from test_kitchen_service import bundle


class JobTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.env=patch.dict('os.environ',{'BLOB_ROOT':str(Path(self.tmp.name)/'files')})
        self.env.start();self.addCleanup(self.env.stop)
        self.hash=patch.object(Accounts,'password_hash',staticmethod(lambda password,salt=None:'0'*32+':test'))
        self.hash.start();self.addCleanup(self.hash.stop)
        self.store=Accounts(Path(self.tmp.name)/'accounts.db');self.addCleanup(self.store.database.close)
        self.token=self.store.register({'login':'alice','nickname':'禾','password':'password123','snapshot':bundle()},'local')
        self.bob=self.store.register({'login':'bob','nickname':'乙','password':'password123','snapshot':bundle()},'local')
        self.jobs=Jobs(self.store)

    def create(self,request='request-001',**extra):
        return self.jobs.create(self.token,{'requestId':request,'kind':'text','input':{'prompt':'番茄炒蛋'},**extra})

    def test_retry_results_keep_same_dish_identity(self):
        job={'id':'one-job'}
        first=stable_recipes(job,{'recipes':[{'id':'random-a','name':'番茄炒蛋','source':'link'}]})
        second=stable_recipes(job,{'recipes':[{'id':'random-b','name':'番茄炒蛋','source':'link'}]})
        self.assertEqual(first['recipes'][0]['id'],second['recipes'][0]['id'])
        self.assertNotEqual(first['recipes'][0]['id'],stable_recipes({'id':'another'},second)['recipes'][0]['id'])

    def test_idempotency_household_access_and_quota(self):
        first=self.create();self.assertEqual(first['id'],self.create()['id'])
        with self.assertRaises(AccountError):self.create(input={'prompt':'别的菜'})
        with self.assertRaises(AccountError):self.jobs.get(self.bob,first['id'])
        self.create('request-002');self.create('request-003')
        with self.assertRaises(AccountError) as error:self.create('request-004')
        self.assertEqual(error.exception.status,429)
        invite=self.store.current(self.token)['household']['invite'];self.store.join(self.bob,{'code':invite})
        self.assertEqual(self.jobs.get(self.bob,first['id'])['id'],first['id'])

    def test_expired_lease_recovery_and_stale_worker_cannot_finish(self):
        item=self.create();first=self.jobs.claim(now=100);self.assertIsNone(self.jobs.claim(now=110))
        second=self.jobs.claim(now=200);self.assertNotEqual(first['lease'],second['lease'])
        self.assertFalse(self.jobs.emit(first,'recipes',{'recipes':[{'name':'过期'}]}))
        self.assertFalse(self.jobs.finish(first,{'recipes':['过期']}))
        self.assertTrue(self.jobs.finish(second,{'recipes':['已完成']}))
        restarted=Jobs(Accounts(self.store.path))
        self.assertEqual(restarted.get(self.token,item['id'])['result']['recipes'],['已完成'])

    def test_concurrent_claims_only_one_worker(self):
        self.create();barrier=threading.Barrier(2)
        def claim():barrier.wait();return self.jobs.claim()
        with ThreadPoolExecutor(2) as pool:values=list(pool.map(lambda _:claim(),range(2)))
        self.assertEqual(sum(value is not None for value in values),1)

    def test_events_survive_failure_retry_and_cancel_invalidates_worker(self):
        item=self.create()
        def fail(job,jobs):jobs.emit(job,'recipes',{'recipes':[{'id':'partial'}]});raise ValueError('模型超时')
        with patch('worker.log.exception'):run_once(self.jobs,fail)
        info=self.jobs.get(self.token,item['id']);self.assertEqual(info['status'],'failed');self.assertEqual(info['events'][-1]['recipes'][0]['id'],'partial')
        self.jobs.action(self.token,item['id'],'retry');job=self.jobs.claim()
        self.jobs.action(self.token,item['id'],'cancel');self.assertFalse(self.jobs.finish(job,{'recipes':[]}))
        self.assertEqual(self.jobs.get(self.token,item['id'])['status'],'cancelled')

    def test_private_input_image_and_media_grants(self):
        out=io.BytesIO();Image.new('RGB',(4,4),'red').save(out,format='PNG')
        with self.store.connect() as db:
            user=self.store.user(db,self.token);url=self.store.files.put(db,user,out.getvalue(),'recipe-input')
        item=self.create(kind='image',input={'image':url});job=self.jobs.claim()
        self.jobs.emit(job,'source',{'media':{'images':[{'asset':'/media/'+'a'*24+'/image-1.jpg'}]}})
        with self.store.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM media_grants').fetchone()[0],1)
        with self.assertRaises(AccountError):self.jobs.create(self.bob,{'requestId':'bob-image-001','kind':'image','input':{'image':url}})

    def test_model_usage_attribution_reaches_batch_threads(self):
        import ai,recipe_batches
        entries=[];context=ai.usage_observer.set(entries.append)
        model_response={'choices':[{'message':{'content':'{"recipes":[]}'}}],'usage':{'prompt_tokens':8,'completion_tokens':4}}
        try:
            with patch('ai._request_json',return_value=model_response):
                recipe_batches.run({},[], 'p','http://model','key','test',Path(self.tmp.name),False,ai.request_json,ai.response_json,lambda *_:[],on_batch=None)
            self.assertEqual(len(entries),1);self.assertEqual(entries[0]['inputTokens'],8)
        finally:ai.usage_observer.reset(context)
