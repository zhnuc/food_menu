import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import server
import pipeline
import sources
import recipes as recipes_domain
import vision


class VisualFlowTests(unittest.TestCase):
    def test_compact_recipe_output_still_validates_quantities(self):
        response={'choices':[{'message':{'content':json.dumps({'recipes':[{'n':'番茄菜','s':1,'i':[['番茄',300,'克','番茄300克'],['盐',5,None,'盐适量'],['辣椒油',0.5,'勺','1/2勺辣椒油']],'t':['炒熟']} ]},ensure_ascii=False)}}]}
        with patch.dict(server.os.environ,{'MODEL_API_KEY':'test'}),patch('pipeline.request_json',return_value=response):
            result=server.parse({'article':'番茄300克，盐适量，1/2勺辣椒油，炒熟'})
        recipe=result['recipes'][0]
        self.assertEqual(recipe['name'],'番茄菜')
        self.assertEqual(recipe['ingredients'][0]['quantity'],300)
        self.assertIsNone(recipe['ingredients'][1]['quantity'])
        self.assertEqual(recipe['ingredients'][2]['quantity'],0.5)
        self.assertEqual(recipe['steps'],['炒熟'])

    def test_separate_models_route_to_vision_and_recipe_calls(self):
        source={'evidence':[{'kind':'article','text':'番茄300克炒熟','locator':'正文'}],'warnings':[]}
        response={'choices':[{'message':{'content':'{"recipes":[]}'}}]}
        config={'MODEL_API_KEY':'test','MODEL_NAME':'shared','VISION_MODEL_NAME':'vision-choice','RECIPE_MODEL_NAME':'recipe-choice'}
        with tempfile.TemporaryDirectory() as tmp,patch('pipeline.RECIPE_CACHE',Path(tmp)),patch.dict(server.os.environ,config),patch('local_media.extract',return_value=source) as vision,patch('pipeline.request_json',return_value=response) as recipe:
            server.parse({'share':'https://xhslink.cn/o/test'})
            self.assertEqual(vision.call_args.args[3],'vision-choice')
            self.assertEqual(recipe.call_args.args[1]['model'],'recipe-choice')
            with patch.dict(server.os.environ,{'VISION_MODEL_NAME':'','RECIPE_MODEL_NAME':' '}):
                server.parse({'share':'https://xhslink.cn/o/test'})
                self.assertEqual(vision.call_args.args[3],'shared')
                self.assertEqual(recipe.call_args.args[1]['model'],'shared')

    def test_source_metadata_and_original_body_enter_recipe_request(self):
        source={'title':'番茄菜','author':'原作者','description':'番茄300克炒熟','platform':'bilibili','evidence':[{'kind':'article','text':'番茄300克炒熟','locator':'完整简介'}],'warnings':[]}
        response={'choices':[{'message':{'content':'{"recipes":[]}'}}]}
        with patch.dict(server.os.environ,{'MODEL_API_KEY':'test'}),patch('pipeline.extract_source',return_value=source),patch('pipeline.request_json',return_value=response) as model:
            server.parse({'share':'https://b23.tv/test','transcript':'旧转录不应传入'})
        body=json.loads(model.call_args.args[1]['messages'][1]['content'])
        self.assertEqual(body['source']['title'],'番茄菜')
        self.assertEqual(body['source']['author'],'原作者')
        self.assertEqual(body['evidence'],source['evidence'])
        self.assertNotIn('旧转录',str(body))

    def test_imported_downloader_patch_is_available_without_full_repository(self):
        import bilinote_adapter
        self.assertTrue((bilinote_adapter.UPSTREAM/'LICENSE').is_file())
        self.assertIsNotNone(bilinote_adapter._patch())

    def test_dynote_collection_uses_vendored_script(self):
        module=sources.video_media._dynote_module()
        self.assertTrue(callable(module.collect_page_info))
        self.assertTrue(callable(module.find_media_url))
