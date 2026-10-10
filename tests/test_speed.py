import json
import tempfile
import unittest
from PIL import Image
from pathlib import Path
from unittest.mock import Mock,patch
import server
import pipeline
import sources
import recipes as recipes_domain
import vision
import local_media


class SpeedTests(unittest.TestCase):
    def test_contact_sheet_preserves_aspect_ratio_and_has_four_numbered_cells(self):
        import base64,io
        from visual_pack import contact_sheet
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp)
            frames=[]
            colors=['red','green','blue','yellow']
            for index,color in enumerate(colors):
                path=directory/f'image-{index:02}.jpg';Image.new('RGB',(320,640),color).save(path)
                frames.append({'asset':'/media/test/'+path.name})
            encoded,size,dimensions=contact_sheet(directory,frames,offset=8,max_edge=320)
            with Image.open(io.BytesIO(base64.b64decode(encoded))) as sheet:
                self.assertEqual(dimensions,sheet.size)
                self.assertEqual(dimensions,(344,720))
                self.assertGreater(size,0)
                for point,color in zip([(80,180),(248,180),(80,536),(248,536)],colors):
                    expected=Image.new('RGB',(1,1),color).getpixel((0,0))
                    actual=sheet.getpixel(point)
                    self.assertLess(max(abs(a-b) for a,b in zip(actual,expected)),10)

    def test_four_contact_sheets_map_sixteen_originals_and_keep_tail(self):
        with tempfile.TemporaryDirectory() as tmp,patch.dict(local_media.os.environ,{'VISION_WORKERS':'1'}):
            directory=Path(tmp)
            for i in range(17):Image.new('RGB',(80,120),(i*10,40,80)).save(directory/f'image-{i:02}.jpg')
            data={'evidence':[],'warnings':[],'images':[{'index':i+1,'asset':f'/media/test/image-{i:02}.jpg'} for i in range(17)]}
            def recognize(endpoint,body,*args,**kwargs):
                content=body['messages'][1]['content']
                count=sum(row['type']=='image_url' for row in content)
                value={'items':[{'id':i,'text':f'食材{i}'} for i in range(16)]} if count==4 else {'text':'末张食材'}
                return {'choices':[{'message':{'content':json.dumps(value)}}]}
            request=Mock(side_effect=recognize)
            result=vision.enrich_visuals(data,directory,'key','https://example.com','vision',request)
            self.assertTrue(result['visionProcessed'])
            self.assertEqual(len(result['visionAssets']),17)
            self.assertEqual(result['evidence'][-1]['asset'],'/media/test/image-16.jpg')
            self.assertEqual(request.call_count,2)
            self.assertEqual(sorted(sum(row['type']=='image_url' for row in c.args[1]['messages'][1]['content']) for c in request.call_args_list),[1,4])

    def test_switching_vision_model_replaces_cached_ocr(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp)
            Image.new('RGB',(80,120),'white').save(directory/'image-00.jpg')
            data={'evidence':[],'warnings':[],'images':[{'index':1,'asset':'/media/test/image-00.jpg'}]}
            first=Mock(return_value={'choices':[{'message':{'content':'{"text":"旧识别"}'}}]})
            vision.enrich_visuals(data,directory,'key','https://example.com','old',first)
            second=Mock(return_value={'choices':[{'message':{'content':'{"text":"肥牛400g"}'}}]})
            vision.enrich_visuals(data,directory,'key','https://example.com','new',second)
            self.assertEqual(second.call_count,1)
            self.assertEqual([e['text'] for e in data['evidence']],['肥牛400g'])
            vision.enrich_visuals(data,directory,'key','https://example.com','new',second)
            self.assertEqual(second.call_count,1)

    def test_gemini_markdown_json_keeps_image_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp)
            Image.new('RGB',(80,120),'white').save(directory/'image-00.jpg')
            data={'evidence':[],'warnings':[],'images':[{'index':1,'asset':'/media/test/image-00.jpg'}]}
            response={'choices':[{'message':{'content':'```json\n{"text":"肥牛400g"}\n```'}}]}
            result=vision.enrich_visuals(data,directory,'key','https://example.com','gemini',Mock(return_value=response))
            self.assertTrue(result['visionProcessed'])
            self.assertEqual(result['evidence'][0]['text'],'肥牛400g')
            self.assertEqual(result['evidence'][0]['asset'],'/media/test/image-00.jpg')

    def test_recipe_cache_reuses_result_but_invalidates_when_evidence_changes(self):
        source={'title':'番茄菜','evidence':[{'kind':'article','text':'番茄300克炒熟','locator':'简介'}],'warnings':[]}
        response={'choices':[{'message':{'content':json.dumps({'recipes':[{'name':'番茄菜','servings':1,'ingredients':[{'name':'番茄','quantity':300,'unit':'克','evidence':'番茄300克'}],'steps':['炒熟']}]},ensure_ascii=False)}}]}
        response['choices'][0]['message']['content']='```json\n'+response['choices'][0]['message']['content']+'\n```'
        with tempfile.TemporaryDirectory() as tmp,patch('pipeline.RECIPE_CACHE',Path(tmp)),patch.dict(server.os.environ,{'MODEL_API_KEY':'test'}),patch('pipeline.extract_source',return_value=source),patch('pipeline.request_json',return_value=response) as model:
            first=server.parse({'share':'https://b23.tv/cache'})
            second=server.parse({'share':'https://b23.tv/cache'})
            self.assertEqual(model.call_count,1)
            self.assertTrue(second['timings']['recipeCacheHit'])
            self.assertNotEqual(first['recipes'][0]['id'],second['recipes'][0]['id'])
            self.assertEqual(second['recipes'][0]['ingredients'][0]['quantity'],300)
            source['evidence'][0]['text']='番茄400克炒熟'
            third=server.parse({'share':'https://b23.tv/cache'})
            self.assertEqual(model.call_count,2)
            self.assertFalse(third['timings']['recipeCacheHit'])
            self.assertIsNone(third['recipes'][0]['ingredients'][0]['quantity'])

    def test_batch_preserves_image_mapping_and_marks_missing_items_for_retry(self):
        with tempfile.TemporaryDirectory() as tmp,patch.dict(local_media.os.environ,{'VISION_BATCH_SIZE':'4'}):
            directory=Path(tmp)
            for i in range(3):Image.new('RGB',(80,120),'white').save(directory/f'image-{i:02}.jpg')
            data={'evidence':[],'warnings':[],'images':[{'index':i+1,'asset':f'/media/test/image-{i:02}.jpg'} for i in range(3)]}
            response={'choices':[{'message':{'content':'{"items":[{"id":2,"text":"土豆200克"},{"id":0,"text":"番茄300克"}]}'}}]}
            request=Mock(return_value=response)
            result=vision.enrich_visuals(data,directory,'key','https://example.com','vision',request)
            self.assertEqual(request.call_count,1)
            self.assertFalse(result['visionProcessed'])
            rows=[e for e in result['evidence'] if e['kind']=='image_ocr']
            self.assertEqual(rows[0]['asset'],'/media/test/image-00.jpg')
            self.assertEqual(rows[1]['asset'],'/media/test/image-02.jpg')
            self.assertEqual(rows[1]['text'],'土豆200克')

    def test_batch_duplicate_ids_are_not_silently_assigned(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp)
            for i in range(2):Image.new('RGB',(80,120),'white').save(directory/f'image-{i:02}.jpg')
            data={'evidence':[],'warnings':[],'images':[{'index':i+1,'asset':f'/media/test/image-{i:02}.jpg'} for i in range(2)]}
            response={'choices':[{'message':{'content':'{"items":[{"id":0,"text":"A"},{"id":0,"text":"B"},{"id":1,"text":"C"}]}'}}]}
            result=vision.enrich_visuals(data,directory,'key','https://example.com','vision',Mock(return_value=response))
            self.assertEqual(result['visionAssets'],['/media/test/image-01.jpg'])
