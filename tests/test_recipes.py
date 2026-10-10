import unittest
from unittest.mock import patch
import server
import pipeline
import sources
import recipes as recipes_domain
import vision

class RecipeTests(unittest.TestCase):
    def recipe(self,ingredients,**extra):
        return dict(name='测试菜',ingredients=ingredients,servings=2,targetServings=4,**extra)
    def item(self,name,q,unit): return dict(name=name,quantity=q,unit=unit)
    def test_weight_alias_scale(self):
        data=server.shopping([self.recipe([self.item('西红柿',300,'克'),self.item('番茄',0.5,'千克')])])
        self.assertEqual(len(data),1);self.assertEqual(data[0]['quantity'],1600)
    def test_onions_and_dimensions(self):
        data=server.shopping([self.recipe([self.item('小葱',2,'根'),self.item('大葱',1,'根'),self.item('小葱',20,'克')])])
        self.assertEqual(len(data),3)
    def test_pending_and_known_remain(self):
        data=server.shopping([self.recipe([self.item('盐',None,''),self.item('盐',3,'克'),self.item('油','适量','')])])
        salt=next(x for x in data if x['name']=='盐')
        oil=next(x for x in data if x['name']=='油')
        self.assertEqual(len(data),2)
        self.assertEqual(salt['quantity'],6);self.assertEqual(salt['pendingCount'],2)
        self.assertIsNone(oil['quantity']);self.assertEqual(oil['pendingCount'],2)
    def test_pending_weights_use_plus_markers(self):
        rows=server.shopping([
            {'name':'A','servings':1,'targetServings':1,'ingredients':[self.item('虾滑',None,'克')]},
            {'name':'B','servings':1,'targetServings':1,'ingredients':[self.item('虾滑',100,'克')]},
            {'name':'C','servings':1,'targetServings':1,'ingredients':[self.item('虾滑',None,'克')]},
        ])
        shrimp=next(x for x in rows if x['name']=='虾滑')
        self.assertEqual(shrimp['quantity'],100)
        self.assertEqual(shrimp['unit'],'克')
        self.assertEqual(shrimp['pendingCount'],2)
    def test_all_pending_weights_get_simple_planning_baseline(self):
        rows=server.shopping([{'name':'测试菜','servings':2,'targetServings':2,'ingredients':[self.item('虾滑',None,'克'),self.item('虾滑',None,'克')]}])
        shrimp=next(x for x in rows if x['name']=='虾滑')
        self.assertEqual(shrimp['quantity'],200)
        self.assertEqual(shrimp['pendingCount'],2)
    def test_invalid_servings(self):
        with self.assertRaises(ValueError):server.shopping([dict(name='菜',servings=0,ingredients=[])])
    def test_missing_key_preserves_evidence(self):
        with patch.dict(server.os.environ,{'MODEL_API_KEY':''}):
            result=server.parse({'article':'番茄300克，切块炒熟'})
            self.assertEqual(result['recipes'],[]);self.assertEqual(result['evidence'][0]['kind'],'article')
    def test_url_allowlist(self):
        with self.assertRaises(ValueError):sources.source_url('https://bilibili.com.attacker.example/BV123')
        self.assertIn('b23.tv',sources.source_url('分享 https://b23.tv/abc'))
    def test_b23_shortlink_expands(self):
        class Response:
            url='https://www.bilibili.com/video/BV1PCHLzREzT/'
            def __enter__(self):return self
            def __exit__(self,*args):pass
        class Opener:
            def open(self,*args,**kwargs):return Response()
        with patch('sources.build_opener',return_value=Opener()):
            self.assertEqual(sources.expand_bili('https://b23.tv/JkH26jl'),'https://www.bilibili.com/video/BV1PCHLzREzT/')
    def test_bili_routes_to_real_media_adapter(self):
        evidence=[{'kind':'video_ocr','text':'番茄切块炒熟','locator':'12s'}]
        with patch('sources.video_media.extract',return_value={'evidence':evidence}) as adapter:
            self.assertEqual(pipeline.extract_source('https://b23.tv/JkH26jl')['evidence'],evidence)
            self.assertEqual(adapter.call_args.args[0],'https://b23.tv/JkH26jl')
    def test_model_quantity_evidence(self):
        result={'choices':[{'message':{'content':'{"recipes":[{"name":"番茄菜","servings":1,"ingredients":[{"name":"番茄","quantity":300,"unit":"克","evidence":"番茄300克"},{"name":"盐","quantity":5,"unit":"克","evidence":"盐适量"}],"steps":["炒熟"]}]}'}}]}
        with patch.dict(server.os.environ,{'MODEL_API_KEY':'test'}),patch('pipeline.request_json',return_value=result):
            data=server.parse({'article':'番茄300克，盐适量，炒熟'})
            self.assertEqual(data['recipes'][0]['ingredients'][0]['quantity'],300)
            self.assertIsNone(data['recipes'][0]['ingredients'][1]['quantity'])
    def test_chinese_numerals_must_match_quoted_unit(self):
        result={'choices':[{'message':{'content':'{"recipes":[{"name":"汤","servings":1,"ingredients":[{"name":"盐","quantity":1,"unit":"勺","evidence":"一勺盐"},{"name":"豆腐","quantity":0.5,"unit":"块","evidence":"半块嫩豆腐"},{"name":"水","quantity":2,"unit":"小碗","evidence":"两小碗清水"}],"steps":["煮沸"]}]}'}}]}
        with patch.dict(server.os.environ,{'MODEL_API_KEY':'test'}),patch('pipeline.request_json',return_value=result):
            data=server.parse({'article':'一勺盐，半块嫩豆腐，两小碗清水'})
        self.assertEqual([i['quantity'] for i in data['recipes'][0]['ingredients']],[1,0.5,2])

if __name__=='__main__':unittest.main()

class MultipleRecipesTests(unittest.TestCase):
    def test_multiple_cards_scaled_and_unconfirmed(self):
        recipes=[{'name':'A','servings':2,'targetServings':4,'ingredients':[{'name':'西红柿','quantity':300,'unit':'克'}]}, {'name':'B','servings':1,'targetServings':1,'ingredients':[{'name':'番茄','quantity':0.5,'unit':'千克'},{'name':'番茄','quantity':None,'unit':'','pending':True}]}]
        items=server.shopping(recipes)
        self.assertEqual(items[0]['quantity'],1100)
        self.assertEqual(items[0]['pendingCount'],1)
        self.assertEqual(items[0]['recipes'],['A','B'])

class RealShareRegressionTests(unittest.TestCase):
    def test_xhs_cn_share_link_recognized(self):
        share='一把青菜，一碗面糊，咕嘟咕嘟煮出锅的家常味道，没有... https://xhslink.cn/o/2sZTKHH5lHP 。复制后直奔小红书，笔记等你来翻。'
        self.assertEqual(sources.source_url(share),'https://xhslink.cn/o/2sZTKHH5lHP')
    def test_share_excerpt_is_not_recipe_evidence(self):
        with patch.dict(server.os.environ,{'MODEL_API_KEY':''}):
            with patch('sources.local_media.extract',side_effect=ValueError('获取失败')):
                result=server.parse({'share':'一把青菜，一碗面糊 https://xhslink.cn/o/2sZTKHH5lHP'})
            self.assertEqual(result['recipes'],[])
            self.assertTrue(result['warnings'])


class MediaAllowlistTests(unittest.TestCase):
    def test_redirect_allowlist(self):
        self.assertFalse(sources.local_media.allowed('https://xiaohongshu.com.attacker.example/'))
        self.assertFalse(sources.local_media.allowed('https://user:pass@xiaohongshu.com/'))

class EggCountMergeTests(unittest.TestCase):
    def test_eggs_pieces_merge_and_notes_survive(self):
        rows=server.shopping([{'name':'A','servings':1,'ingredients':[{'name':'鸡蛋','quantity':2,'unit':'个'}]},{'name':'B','servings':1,'ingredients':[{'name':'鸡蛋','quantity':1,'unit':'颗','note':'原画面计量'}]}])
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['quantity'],3)
        self.assertIn('原画面计量',rows[0]['notes'])
