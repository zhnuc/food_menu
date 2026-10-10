import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock,patch
import local_media
import recipe_batches
import server
import pipeline
import sources
import recipes as recipes_domain
import vision
from PIL import Image


class RecipeBatchTests(unittest.TestCase):
    def evidence(self,count=12):
        return [{'kind':'image_ocr','dish':f'菜{i}','standalone':True,'text':f'食材{i}100克炒熟','locator':f'第{i//2+1}张配图','asset':f'image-{i//2}.jpg'} for i in range(count)]

    def response(self,body):
        data=json.loads(body['messages'][1]['content'])
        return {'choices':[{'message':{'content':json.dumps({'recipes':[{'n':name,'s':1,'i':[],'t':['炒熟']} for name in data['dishNames']]})}}]}

    def test_twelve_dishes_use_four_overlapping_calls_and_keep_order(self):
        barrier=threading.Barrier(4);calls=[];guard=threading.Lock()
        def request(endpoint,body,*args,**kwargs):
            data=json.loads(body['messages'][1]['content'])
            with guard:calls.append(data)
            barrier.wait(timeout=3)
            return self.response(body)
        with tempfile.TemporaryDirectory() as tmp,patch.dict(server.os.environ,{'MODEL_API_KEY':'test','RECIPE_BATCH_SIZE':'3','RECIPE_WORKERS':'4'}),patch('pipeline.RECIPE_CACHE',Path(tmp)),patch('pipeline.extract_source',return_value={'images':[{}],'evidence':self.evidence(),'warnings':[]}),patch('pipeline.request_json',side_effect=request):
            result=server.parse({'share':'https://v.douyin.com/test'})
        self.assertEqual(result['timings']['recipeGroups'],4)
        self.assertEqual(result['timings']['recipeRoute'],'parallel')
        self.assertEqual(result['timings']['recipeFailedGroups'],0)
        self.assertEqual(len(calls),4)
        self.assertEqual([r['name'] for r in result['recipes']],[f'菜{i}' for i in range(12)])
        self.assertTrue(all(len(call['dishNames'])==3 for call in calls))
        self.assertTrue(all({e['dish'] for e in call['evidence']}==set(call['dishNames']) for call in calls))

    def test_video_frames_and_same_dish_across_pages_stay_together(self):
        video=[{'kind':'video_ocr','text':'1勺盐'},{'kind':'video_ocr','text':'煮5分钟'}]
        self.assertEqual(recipe_batches.groups(video),[(video,[])])
        photo=self.evidence(4);photo.append({**photo[0],'text':'中火煮5分钟'})
        batches=recipe_batches.groups(photo)
        self.assertEqual(sum(row.get('dish')=='菜0' for row in batches[0][0]),2)
        self.assertEqual(batches[0][1],['菜0','菜1','菜2'])

    def test_failed_group_is_reported_and_only_it_is_retried(self):
        def request(endpoint,body,*args,**kwargs):
            names=json.loads(body['messages'][1]['content'])['dishNames']
            if names[0]=='菜3':raise ValueError('模拟失败')
            return self.response(body)
        with tempfile.TemporaryDirectory() as tmp,patch.dict(server.os.environ,{'MODEL_API_KEY':'test','RECIPE_BATCH_SIZE':'3','RECIPE_WORKERS':'4'}),patch('pipeline.RECIPE_CACHE',Path(tmp)),patch('pipeline.extract_source',return_value={'images':[{}],'evidence':self.evidence(6),'warnings':[]}):
            with patch('pipeline.request_json',side_effect=request):first=server.parse({'share':'https://v.douyin.com/test'})
            self.assertEqual(len(first['recipes']),3)
            self.assertEqual(first['timings']['recipeFailedGroups'],1)
            self.assertTrue(first['warnings'])
            with patch('pipeline.request_json',side_effect=lambda endpoint,body,*args,**kwargs:self.response(body)) as retry:
                second=server.parse({'share':'https://v.douyin.com/test'})
            self.assertEqual(retry.call_count,1)
            self.assertEqual(len(second['recipes']),6)
            self.assertEqual(second['timings']['recipeFailedGroups'],0)

    def test_photo_recipes_keep_shared_asset_but_separate_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp);Image.new('RGB',(80,120),'white').save(directory/'image-00.jpg')
            response={'choices':[{'message':{'content':json.dumps({'dishes':[['菜A','番茄100克炒熟',True],['菜B','土豆200克炖熟',True]]},ensure_ascii=False)}}]}
            data={'title':'原帖标题','images':[{'index':1,'asset':'/media/test/image-00.jpg'}],'evidence':[],'warnings':[]}
            request=Mock(return_value=response)
            result=vision.enrich_visuals(data,directory,'key','https://example.com','vision',request)
            self.assertEqual([e['dish'] for e in result['evidence']],['菜A','菜B'])
            self.assertEqual(len(set(e['asset'] for e in result['evidence'])),1)
            self.assertEqual(len(result['visionAssets']),1)
            self.assertTrue(result['visionProcessed'])
            self.assertTrue(all(e['standalone'] for e in result['evidence']))
            self.assertIn('原帖标题',request.call_args.args[1]['messages'][1]['content'][0]['text'])

    def test_unnamed_or_partial_or_legacy_segment_keeps_entire_post(self):
        for segment in [
            {'kind':'image_ocr','text':'加水炖40分钟'},
            {'kind':'image_ocr','dish':'调汁','standalone':False,'text':'1勺生抽'},
            {'kind':'image_ocr','dish':'另一道菜','text':'土豆200克'},
            {'kind':'image_ocr','dish':'另一道菜','standalone':'true','text':'土豆200克'},
            {'kind':'frame','text':'尚待识别'},
            {'kind':'subtitle','text':'所有菜共用这一份酱汁'},
        ]:
            with self.subTest(segment=segment):
                rows=self.evidence(6)+[segment]
                self.assertEqual(recipe_batches.groups(rows),[(rows,[])])

    def test_twelve_continuation_images_make_one_request_with_all_steps(self):
        evidence=[{'kind':'article','text':'红烧肉分步教程'}]
        evidence.extend({'kind':'image_ocr','dish':('红烧肉' if i==0 else ''),'standalone':False,
                         'text':('五花肉500克' if i==0 else f'步骤{i}'), 'asset':f'image-{i}.jpg'} for i in range(12))
        response={'choices':[{'message':{'content':json.dumps({'recipes':[{'n':'红烧肉','s':1,'i':[['五花肉',500,'克','五花肉500克']],'t':[f'步骤{i}' for i in range(1,12)]}]},ensure_ascii=False)}}]}
        with tempfile.TemporaryDirectory() as tmp,patch.dict(server.os.environ,{'MODEL_API_KEY':'test'}),patch('pipeline.RECIPE_CACHE',Path(tmp)),patch('pipeline.extract_source',return_value={'images':[{}],'evidence':evidence,'warnings':[]}),patch('pipeline.request_json',return_value=response) as model:
            result=server.parse({'share':'https://v.douyin.com/continuation','refreshRecipe':True})
        model.assert_called_once()
        request=json.loads(model.call_args.args[1]['messages'][1]['content'])
        self.assertEqual(request['evidence'],evidence)
        self.assertNotIn('dishNames',request)
        self.assertEqual(result['timings']['recipeRoute'],'whole')
        self.assertEqual(result['timings']['recipeGroups'],1)
        self.assertEqual(len(result['recipes']),1)
        self.assertEqual(len(result['recipes'][0]['steps']),11)
        self.assertEqual(result['recipes'][0]['ingredients'][0]['quantity'],500)

    def test_vision_preserves_unnamed_and_legacy_text_without_claiming_independence(self):
        for portions in [ [['','1勺盐',True]], [['红烧肉','1勺盐',False]], [['红烧肉','1勺盐']] ]:
            with self.subTest(portions=portions),tempfile.TemporaryDirectory() as tmp:
                directory=Path(tmp);Image.new('RGB',(80,120),'white').save(directory/'image-00.jpg')
                data={'images':[{'index':1,'asset':'/media/test/image-00.jpg'}],'evidence':[],'warnings':[]}
                response={'choices':[{'message':{'content':json.dumps({'dishes':portions},ensure_ascii=False)}}]}
                result=vision.enrich_visuals(data,directory,'key','https://example.com','vision',Mock(return_value=response))
                self.assertEqual(result['evidence'][0]['text'],'1勺盐')
                self.assertFalse(result['evidence'][0]['standalone'])

    def test_duplicate_recipe_fragments_are_not_silently_discarded(self):
        response={'choices':[{'message':{'content':json.dumps({'recipes':[
            {'n':'红烧肉','s':1,'i':[],'t':['焯水']},
            {'n':'红烧肉','s':1,'i':[],'t':['炖40分钟']}]},ensure_ascii=False)}}]}
        with patch.dict(server.os.environ,{'MODEL_API_KEY':'test'}),patch('pipeline.request_json',return_value=response):
            with self.assertRaisesRegex(ValueError,'同名菜谱'):
                server.parse({'article':'红烧肉，先焯水再炖40分钟'})
