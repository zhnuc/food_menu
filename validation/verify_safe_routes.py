"""Verify deployed routes and ambiguous continuation text with real model calls."""
import json
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'validation'))
import server
import pipeline
import sources
import recipes as recipes_domain
import vision
from compare_recipe_routes import check_quality

sys.stdout.reconfigure(encoding='utf-8')


def api(path,body):
    with urlopen(Request('http://127.0.0.1:8767'+path,data=json.dumps(body).encode(),
                        headers={'Content-Type':'application/json'}),timeout=180) as response:
        return json.load(response)


def save(label,data):
    (ROOT/'validation'/('safe-route-'+label+'.json')).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')


photo=json.loads((ROOT/'validation/safe-route-photo-http.json').read_text(encoding='utf-8'))
assert photo['timings']['recipeRoute']=='parallel'
assert photo['timings']['recipeGroups']==4
assert photo['timings']['recipeFailedGroups']==0
assert all(check_quality('twelve_dishes',photo['recipes']).values())
beans=next(r for r in photo['recipes'] if r['name']=='豆角炖土豆')
assert any(i['name']=='生抽' and i['quantity']==2 and i['unit']=='勺' for i in beans['ingredients'])
assert '2勺生抽' not in next(e['text'] for e in photo['evidence'] if e.get('dish')=='菠萝咕咾肉')

start=time.perf_counter()
video=api('/api/parse',{'share':'https://xhslink.cn/o/2sZTKHH5lHP','refreshRecipe':True})
video_wall=round(time.perf_counter()-start,3)
save('video-http',video)
assert video['timings']['recipeRoute']=='whole'
assert video['timings']['recipeGroups']==1
assert all(check_quality('single_continuation',video['recipes']).values())

# Real video OCR represented as unnamed photo steps. The raw content is kept;
# this is a text-routing regression, not extraction of a real photo post.
evidence=[]
for index,row in enumerate(video['evidence']):
    if row['kind']=='video_ocr':
        row={**row,'kind':'image_ocr','standalone':False}
        if index==2:row['dish']='菜坨坨'
        elif '卷起蛋皮' in row['text']:row['dish']='蛋皮'
        elif '1勺生抽' in row['text']:row['dish']='调汁'
    evidence.append(row)
fixture={**video['media'],'evidence':evidence,'warnings':[]}
calls=[];request=pipeline.request_json
def counted(endpoint,body,*args,**kwargs):
    calls.append(body)
    return request(endpoint,body,*args,**kwargs)
start=time.perf_counter()
with patch('pipeline.extract_source',return_value=fixture),patch('pipeline.request_json',side_effect=counted):
    continuation=server.parse({'share':'https://xhslink.cn/o/2sZTKHH5lHP','refreshRecipe':True})
continuation_wall=round(time.perf_counter()-start,3)
save('continuation-text',continuation)
assert len(calls)==1
assert isinstance(calls[0]['messages'][1]['content'],str)
request_data=json.loads(calls[0]['messages'][1]['content'])
assert request_data['evidence']==evidence and 'dishNames' not in request_data
assert continuation['timings']['recipeRoute']=='whole'
assert all(check_quality('single_continuation',continuation['recipes']).values())

cached=api('/api/parse',{'share':'https://v.douyin.com/FR1-qclk0O8/'})
save('photo-cached-http',cached)
assert len(cached['recipes'])==12 and cached['timings']['recipeRequests']==0
assert cached['timings']['recipeCacheHit']
shopping=api('/api/shopping',{'recipes':photo['recipes']})
save('shopping-http',shopping)
summary={'photo':{'recipeCount':len(photo['recipes']),'timings':photo['timings'],'checks':check_quality('twelve_dishes',photo['recipes'])},
         'video':{'recipeCount':len(video['recipes']),'wallSeconds':video_wall,'timings':video['timings'],'checks':check_quality('single_continuation',video['recipes'])},
         'continuationText':{'recipeCount':len(continuation['recipes']),'wallSeconds':continuation_wall,'timings':continuation['timings'],
                             'modelRequests':len(calls),'allEvidencePreserved':request_data['evidence']==evidence,
                             'rawImagesSent':False,'checks':check_quality('single_continuation',continuation['recipes'])},
         'cachedPhoto':cached['timings'],'shopping':shopping,
         'note':'Continuations use real video OCR as photo rows; not an actual 12-photo post. First incomplete photo run was retained separately.'}
save('validation',summary)
print(json.dumps({k:v for k,v in summary.items() if k!='shopping'},ensure_ascii=False),flush=True)
