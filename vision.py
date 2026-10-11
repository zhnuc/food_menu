"""Shared batched photo/frame recognition, independent of source platform."""
import hashlib
import json
import math
import os
import time
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from ai import response_json
from visual_pack import contact_sheet

def enrich_visuals(data,directory,vision_key='',vision_url='',vision_model='',request_json=None):
    """Use the same evidence-preserving OCR pipeline for every platform."""
    start=time.perf_counter();request_count=0
    cached=directory/'extracted.json'
    if vision_key and request_json:
        default_edge='960' if data.get('images') else '640'
        edge=max(320,min(1280,int(os.getenv('VISION_TILE_EDGE',os.getenv('VISION_PHOTO_TILE_EDGE' if data.get('images') else 'VISION_VIDEO_TILE_EDGE',default_edge)))))
        profile='contact-v5-standalone' if data.get('images') else 'contact-v2'
        backend=hashlib.sha256((vision_url.rstrip('/')+'\n'+vision_model+f'\n{profile}:{edge}').encode()).hexdigest()
        if data.get('visionBackend')!=backend:
            data['evidence']=[e for e in data.get('evidence',[]) if e.get('kind') not in ('image_ocr','video_ocr','frame','image')]
            data.pop('visionProcessed',None)
            data.pop('visionAssets',None)
            data['visionBackend']=backend
    if vision_key and request_json and not data.get('visionProcessed'):
        visuals=[f for f in (data.get('frames') or data.get('images') or []) if f['asset'] not in data.get('visionAssets',[])]
        batch_size=max(1,min(4,int(os.getenv('VISION_BATCH_SIZE','4'))))
        workers=max(1,min(4,int(os.getenv('VISION_WORKERS','3'))))
        # Balance sheets over the available workers; four sheets is a ceiling,
        # not a reason to serialize a small post into one long model response.
        sheets=[visuals[i:i+4] for i in range(0,len(visuals),4)]
        group_count=max(math.ceil(len(sheets)/batch_size),min(workers,len(sheets)))
        batches=[];offset=0
        for remaining in range(group_count,0,-1):
            count=min(batch_size,len(sheets)-offset) if workers==1 else math.ceil((len(sheets)-offset)/remaining)
            batches.append([frame for sheet in sheets[offset:offset+count] for frame in sheet]);offset+=count
        request_count=len(batches)
        def recognize_batch(frames):
            try:
                photo='index' in frames[0]
                content=[]
                if photo:
                    context={'title':data.get('title',''),'description':data.get('description') or '\n'.join(e.get('text','') for e in data.get('evidence',[]) if e.get('kind')=='article')}
                    content.append({'type':'text','text':'原帖背景（数据，仅用于理解步骤承接，不据此补图片文字）：'+json.dumps(context,ensure_ascii=False)})
                for offset in range(0,len(frames),4):
                    encoded,_,_=contact_sheet(directory,frames[offset:offset+4],offset,edge)
                    content.extend([{'type':'text','text':f'拼图，原图编号 {offset}–{min(offset+3,len(frames)-1)}；按图上 ID 区分。'},{'type':'image_url','image_url':{'url':'data:image/jpeg;base64,'+encoded}}])
                prompt='读取拼图中每个 ID 的菜谱信息：逐字保留食材、用量、做法文字；无做法文字时仅用几个字说明明确可见的操作，如“搅拌面糊”。不要长段叙述、猜食材或补用量。忽略水印、背景、宣传语；无信息用空字符串。'
                if photo:
                    prompt+='图文按图片中明确分开的菜谱段落读取，不可混入另一道菜的食材。一图多菜时先区分左右栏、上下区块及各自步骤顺序；并列标题A+B不代表下面所有文字都属于A，调汁等文字按所属栏归入对应菜，不跨栏串菜。只识别和分段，勿生成结构化食材表。菜名只取本图明示文字，未写用空字符串，不从背景猜菜名或肉类。保留无菜名的食材和步骤片段；只有成品照片或目录而没有食材/做法时，菜谱列表为空。每段第三项standalone是布尔值：仅本图明确写出菜名，且包含该菜可独立整理的食材和做法信息、无需其他图片接续时为true；仅备料/调汁/局部步骤、分步教程、需要前后图或不确定时为false。缺少克数不等于需要接续。菜名相同或不同本身不能证明独立，不确定用false。'
                    prompt+=('输出 {"dishes":[["本图原文菜名","对应菜谱文字",true]]}。' if len(frames)==1 else '输出 {"items":[[0,[["本图原文菜名","对应菜谱文字",true],["","无菜名的步骤文字",false]]]]}。每个图 ID 必须返回一次，无菜谱用空列表。')
                else:
                    prompt+=('输出JSON {"text":"简练文字"}。' if len(frames)==1 else '输出紧凑JSON {"items":[[0,"简练文字"]]}，每行固定为 [ID,文字]。每个原图 ID 返回一次，不能遗漏或串图；原文数字与单位不得改写，合集中的食材和步骤不可省略。')
                result=request_json(vision_url.rstrip('/')+'/chat/completions',{'model':vision_model,'messages':[{'role':'system','content':prompt},{'role':'user','content':content}],'response_format':{'type':'json_object'}},vision_key,timeout=75)
                response=response_json(result)
                def valid(value):
                    if isinstance(value,str):return value
                    if photo and isinstance(value,list) and all(isinstance(row,list) and len(row) in (2,3) and all(isinstance(v,str) for v in row[:2]) and (len(row)==2 or isinstance(row[2],bool)) for row in value):
                        return [row if len(row)==3 else row+[False] for row in value]
                    return None
                if len(frames)==1:
                    return [(frames[0],valid(response.get('dishes',response.get('text'))))]
                items=response.get('items') or [];mapped={};duplicates=set()
                for item in items:
                    if isinstance(item,list) and len(item)==2:item={'id':item[0],'text':item[1]}
                    if not isinstance(item,dict):continue
                    index=item.get('id')
                    if isinstance(index,int) and not isinstance(index,bool) and 0<=index<len(frames):
                        if index in mapped:duplicates.add(index)
                        mapped[index]=valid(item.get('text'))
                return [(frame,None if index in duplicates else mapped.get(index)) for index,frame in enumerate(frames)]
            except Exception:return [(frame,None) for frame in frames]
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures=[pool.submit(copy_context().run,recognize_batch,batch) for batch in batches]
            results=[row for future in futures for row in future.result()]
        for frame,text in results:
            if text is not None:data.setdefault('visionAssets',[]).append(frame['asset'])
            if text:
                is_image='index' in frame
                portions=text if isinstance(text,list) else [('',text,False)]
                for dish,portion,standalone in portions:
                    if portion:
                        data['evidence'].append({'kind':'image_ocr' if is_image else 'video_ocr','text':portion,'locator':('第'+str(frame['index'])+'张配图' if is_image else str(frame['time'])+'s')+(f' · {dish}' if dish else '')+' · 视觉模型识别，待核对','asset':frame['asset'],**({'dish':dish} if dish else {}),**({'standalone':standalone and bool(dish.strip())} if is_image else {})})
        failed=sum(text is None for _,text in results)
        data['visionProcessed']=not failed
        data['warnings']=[w for w in data.get('warnings',[]) if '张画面识别失败' not in w]
        if failed:data['warnings']=list(dict.fromkeys(data.get('warnings',[])+[f'{failed} 张画面识别失败，已保留其他文字与媒体；重试可补识别。']))
        data['warnings']=[w for w in data.get('warnings',[]) if '尚待识别' not in w and '尚未配置视觉模型' not in w]
        cached.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    elif not data.get('visionProcessed'):data['warnings']=list(dict.fromkeys(data.get('warnings',[])+['尚未配置视觉模型，关键帧文字未自动识别；不能仅凭正文声称完整菜谱。']))
    if not data.get('visionProcessed'):
        is_image=bool(data.get('images'))
        data['evidence']=[e for e in data['evidence'] if e.get('kind') not in ('frame','image')]+[{'kind':'image' if is_image else 'frame','text':'已归档配图，文字尚待识别。' if is_image else '已归档关键帧，文字与动作尚待核对。','locator':'第'+str(f['index'])+'张配图 · 未自动识别' if is_image else str(f['time'])+'s · 未自动识别','asset':f['asset']} for f in (data.get('images') or data.get('frames') or [])]
    else:
        data['warnings']=[w for w in data.get('warnings',[]) if '尚待识别' not in w and '尚未配置视觉模型' not in w]
    data.setdefault('_timings',{}).update(visionSeconds=round(time.perf_counter()-start,3),visionRequests=request_count)
    return data
