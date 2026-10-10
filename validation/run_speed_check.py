"""Time actual recipe calls; optionally rerun OCR in an isolated media cache."""
import argparse
import hashlib
import json
import shutil
import sys
import tempfile
import time
import threading
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import server
import pipeline
import sources
import recipes as recipes_domain
import vision
sys.stdout.reconfigure(encoding='utf-8')

def run(url,label):
    calls=[];responses=[];guard=threading.Lock();real_request=pipeline.request_json
    def timed_request(endpoint,body=None,*args,**kwargs):
        start=time.perf_counter()
        messages=(body or {}).get('messages',[])
        vision=any(isinstance(m.get('content'),list) for m in messages)
        try:result=real_request(endpoint,body,*args,**kwargs)
        except Exception as exc:
            with guard:
                row={'stage':'vision' if vision else 'recipe','seconds':round(time.perf_counter()-start,3),'error':type(exc).__name__,'httpStatus':getattr(exc,'code',None)}
                calls.append(row);responses.append(row)
                (ROOT/'validation'/f'speed-{label}-responses.json').write_text(json.dumps(responses,ensure_ascii=False,indent=2),encoding='utf-8')
            raise
        usage=result.get('usage') or {}
        row={'stage':'vision' if vision else 'recipe','seconds':round(time.perf_counter()-start,3),'outputTokens':usage.get('completion_tokens'),'inputTokens':usage.get('prompt_tokens'),'reasoningTokens':(usage.get('completion_tokens_details') or {}).get('reasoning_tokens')}
        if vision:row['imageCount']=sum(x.get('type')=='image_url' for m in messages if isinstance(m.get('content'),list) for x in m['content'])
        elif isinstance((body or {}).get('messages',[{}])[-1].get('content'),str):
            try:row['dishNames']=json.loads(body['messages'][-1]['content']).get('dishNames',[])
            except ValueError:pass
        with guard:
            calls.append(row);responses.append({**row,'content':result.get('choices',[{}])[0].get('message',{}).get('content','')})
            (ROOT/'validation'/f'speed-{label}-responses.json').write_text(json.dumps(responses,ensure_ascii=False,indent=2),encoding='utf-8')
        return result
    start=time.perf_counter()
    with patch('pipeline.request_json',side_effect=timed_request),patch('sources.request_json',side_effect=timed_request):
        data=server.parse({'share':url,'refreshRecipe':True})
    (ROOT/'validation'/f'speed-{label}-recipes.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    result={'label':label,'url':url,'totalSeconds':round(time.perf_counter()-start,3),'calls':calls,'timings':data.get('timings'),'recipes':[r['name'] for r in data['recipes']],'warnings':data['warnings']}
    (ROOT/'validation'/f'speed-{label}.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False),flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('url');parser.add_argument('label');parser.add_argument('--cold-vision',action='store_true');parser.add_argument('--cold-source',action='store_true');parser.add_argument('--recipe-only');args=parser.parse_args()
    print('测速开始：'+args.label,flush=True)
    if args.recipe_only:
        previous=json.loads(Path(args.recipe_only).read_text(encoding='utf-8'))
        source={**previous.get('media',{}),'evidence':previous['evidence'],'warnings':[]}
        with patch('pipeline.extract_source',return_value=source):run(args.url,args.label)
    elif args.cold_source:
        with tempfile.TemporaryDirectory(prefix='recipe-first-') as tmp:
            module=sources.local_media if sources.local_media.allowed(args.url) else sources.video_media
            with patch.object(module,'DATA',Path(tmp)):run(args.url,args.label)
    elif args.cold_vision:
        kind=sources.video_media.platform(args.url)
        note=hashlib.sha256((kind+':'+args.url).encode()).hexdigest()[:24]
        with tempfile.TemporaryDirectory(prefix='recipe-speed-') as tmp:
            destination=Path(tmp)/note
            shutil.copytree(ROOT/'data'/note,destination)
            file=destination/'extracted.json';data=json.loads(file.read_text(encoding='utf-8'))
            data['evidence']=[e for e in data['evidence'] if e['kind'] not in ('video_ocr','image_ocr','transcript','frame','image')]
            for field in ['visionProcessed','visionAssets']:data.pop(field,None)
            file.write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')
            with patch('sources.video_media.DATA',Path(tmp)):run(args.url,args.label)
    else:run(args.url,args.label)
