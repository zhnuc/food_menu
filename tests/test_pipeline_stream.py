import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.request import Request, urlopen
from unittest.mock import patch
from http.server import ThreadingHTTPServer
import pipeline
import server
from contracts import SourcePost, shared_evidence


class StreamTests(unittest.TestCase):
    def evidence(self):
        return [{'kind':'article','text':'原帖正文'}]+[
            {'kind':'image_ocr','dish':f'菜{i}','standalone':True,'text':f'食材{i}100克炒熟','asset':f'image-{i}.jpg'}
            for i in range(12)]

    def response(self, body):
        data=json.loads(body['messages'][1]['content'])
        return {'choices':[{'message':{'content':json.dumps({'recipes':[
            {'n':name,'s':1,'i':[],'t':['炒熟']} for name in data['dishNames']]})}}]}

    def test_source_contract_and_stable_shared_ids(self):
        post=SourcePost.from_mapping('https://b23.tv/test',{'title':'标题','evidence':[{'kind':'article','text':'正文'}]})
        self.assertEqual(post.context['description'],'正文')
        self.assertEqual(post.media,{'title':'标题'})
        rows=shared_evidence([{'kind':'article','text':'正文'},{'text':'正文','kind':'article'}])
        self.assertEqual(len(rows),1)
        self.assertEqual(rows,shared_evidence(rows))
        with self.assertRaises(ValueError):SourcePost.from_mapping('',{'evidence':[{'kind':'article','text':None}]})

    def test_first_validated_batch_arrives_before_remaining_work_and_ids_stay_stable(self):
        gate=threading.Event();barrier=threading.Barrier(4);events=[]
        def request(endpoint,body,*args,**kwargs):
            names=json.loads(body['messages'][1]['content'])['dishNames']
            barrier.wait(timeout=4)
            if names[0]!='菜0':self.assertTrue(gate.wait(timeout=4))
            return self.response(body)
        def event(kind,data):
            events.append((kind,data))
            if kind=='recipes' and not gate.is_set():
                self.assertEqual(data['completedGroups'],1)
                self.assertEqual(len(data['recipes']),3)
                gate.set()
        with tempfile.TemporaryDirectory() as tmp,patch('pipeline.RECIPE_CACHE',Path(tmp)),patch.dict(pipeline.os.environ,{'MODEL_API_KEY':'test','RECIPE_BATCH_SIZE':'3','RECIPE_WORKERS':'4'}),patch('pipeline.extract_source',return_value={'evidence':self.evidence()}),patch('pipeline.request_json',side_effect=request):
            result=pipeline.parse({'share':'https://b23.tv/test','refreshRecipe':True},on_event=event)
        sent=[r for kind,data in events if kind=='recipes' for r in data['recipes']]
        self.assertEqual(len(sent),12)
        self.assertEqual({r['id'] for r in sent},{r['id'] for r in result['recipes']})
        self.assertEqual([r['name'] for r in result['recipes']],[f'菜{i}' for i in range(12)])
        registry={row['id']:row for row in result['evidence']}
        self.assertEqual(len(registry),13)
        for card in result['recipes']:
            self.assertNotIn('evidence',card)
            self.assertEqual(len(card['evidenceIds']),2)
            own=[registry[i] for i in card['evidenceIds'] if registry[i]['kind']=='image_ocr']
            self.assertEqual([e['dish'] for e in own],[card['name']])

    def test_http_flushes_cards_before_done_without_resending_evidence(self):
        gate=threading.Event();barrier=threading.Barrier(4)
        def request(endpoint,body,*args,**kwargs):
            names=json.loads(body['messages'][1]['content'])['dishNames']
            barrier.wait(timeout=4)
            if names[0]!='菜0':gate.wait(timeout=5)
            return self.response(body)
        class QuietHandler(server.Handler):
            def log_message(self,*args):pass
        http=ThreadingHTTPServer(('127.0.0.1',0),QuietHandler)
        worker=threading.Thread(target=http.serve_forever,daemon=True);worker.start()
        try:
            with tempfile.TemporaryDirectory() as tmp,patch('pipeline.RECIPE_CACHE',Path(tmp)),patch.dict(pipeline.os.environ,{'MODEL_API_KEY':'test','RECIPE_BATCH_SIZE':'3','RECIPE_WORKERS':'4'}),patch('pipeline.extract_source',return_value={'evidence':self.evidence()}),patch('pipeline.request_json',side_effect=request):
                req=Request(f'http://127.0.0.1:{http.server_port}/api/parse',data=json.dumps({'share':'https://b23.tv/test','refreshRecipe':True}).encode(),headers={'Content-Type':'application/json','Accept':'application/x-ndjson'})
                with urlopen(req,timeout=8) as response:
                    events=[]
                    while True:
                        item=json.loads(response.readline());events.append(item)
                        if item['type']=='recipes':break
                    self.assertFalse(gate.is_set())
                    self.assertEqual(len(events[-1]['recipes']),3)
                    gate.set()
                    events.extend(json.loads(line) for line in response)
            self.assertEqual([e['type'] for e in events].count('source'),1)
            self.assertEqual(events[-1]['type'],'done')
            self.assertNotIn('recipes',events[-1])
            self.assertNotIn('evidence',events[-1])
            self.assertEqual(sum(len(e.get('recipes',[])) for e in events),12)
        finally:
            gate.set();http.shutdown();http.server_close();worker.join(timeout=2)

    def test_partial_failures_keep_successful_events_and_cached_retry(self):
        evidence=self.evidence()[0:7];events=[]
        def request(endpoint,body,*args,**kwargs):
            if json.loads(body['messages'][1]['content'])['dishNames'][0]=='菜3':raise ValueError('模拟失败')
            return self.response(body)
        with tempfile.TemporaryDirectory() as tmp,patch('pipeline.RECIPE_CACHE',Path(tmp)),patch.dict(pipeline.os.environ,{'MODEL_API_KEY':'test'}),patch('pipeline.extract_source',return_value={'evidence':evidence}):
            with patch('pipeline.request_json',side_effect=request):
                first=pipeline.parse({'share':'https://b23.tv/test'},on_event=lambda kind,data:events.append((kind,data)))
            self.assertEqual(first['timings']['recipeFailedGroups'],1)
            self.assertEqual(sum(len(data['recipes']) for kind,data in events if kind=='recipes'),3)
            with patch('pipeline.request_json',side_effect=lambda endpoint,body,*args,**kwargs:self.response(body)) as retry:
                second=pipeline.parse({'share':'https://b23.tv/test'})
            self.assertEqual(retry.call_count,1)
            self.assertEqual(len(second['recipes']),6)
