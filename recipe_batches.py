"""Split only self-contained photo recipes; retain ambiguous post context."""
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextvars import copy_context


def groups(evidence, batch_size=3):
    dishes={};shared=[]
    photos=[row for row in evidence if row.get('kind')=='image_ocr']
    # A dish name alone does not prove independence. Any unnamed, legacy or
    # continuation segment must keep the whole post together, including names.
    if not photos or any(not isinstance(row.get('dish'),str) or not row['dish'].strip() or row.get('standalone') is not True for row in photos):
        return [(evidence,[])]
    if any(row.get('kind') in ('video_ocr','subtitle','image','frame') for row in evidence):
        return [(evidence,[])]
    for row in evidence:
        if row.get('kind')=='image_ocr':
            name=row['dish'].strip()
            dishes.setdefault(name,[]).append(row)
        else:shared.append(row)
    if len(dishes)<=batch_size:return [(evidence,[])]
    names=list(dishes);batches=[]
    for start in range(0,len(names),batch_size):
        selected=names[start:start+batch_size]
        batches.append((shared+[row for name in selected for row in dishes[name]],selected))
    return batches


def run(source,evidence,prompt,endpoint,key,model,cache,refresh,request_json,decode,validate,batch_size=3,workers=4,on_batch=None):
    batches=groups(evidence,batch_size)
    def process(batch):
        rows,names=batch
        content=json.dumps({'source':source,'evidence':rows,**({'dishNames':names} if names else {})},ensure_ascii=False)
        instruction=prompt+('本次只整理dishNames列出的菜，逐一返回且菜名保持一致。source是背景，不得从中额外生成其他菜。' if names else '本次保留整篇上下文：结合正文和证据顺序判断菜谱归属，无菜名的备料、调汁、烹饪、装盘片段不是独立菜。同一道菜的所有片段合并为一张完整菜谱，不得按图片数或dish提示强行拆菜，不得猜测未说明的具体肉类。standalone=false只表示需要上下文，不是无效证据，不能因此漏掉有明确食材或做法的菜；完整遍历所有段落。')
        fingerprint=hashlib.sha256(json.dumps([instruction,content,model,endpoint,key],ensure_ascii=False).encode()).hexdigest()
        path=cache/(fingerprint+'.json');hit=False
        try:
            if source.get('url') and not refresh and path.exists():
                try:data=json.loads(path.read_text(encoding='utf-8'));hit=True
                except (ValueError,OSError):pass
            if not hit:
                result=request_json(endpoint,{'model':model,'messages':[{'role':'system','content':instruction},{'role':'user','content':content}],'response_format':{'type':'json_object'},'max_tokens':8192},key,timeout=120)
                data=decode(result)
            recipes=validate(data,rows)
            returned_names=[r['name'].strip() for r in recipes]
            if len(returned_names)!=len(set(returned_names)):raise ValueError('整理结果重复拆出同名菜谱，需要合并完整步骤后重试。')
            if names and {r['name'].strip() for r in recipes}!=set(names):raise ValueError('整理结果缺少分配的菜谱或混入其他菜，重试可补齐。')
            if source.get('url') and recipes and not hit:
                import uuid
                cache.mkdir(parents=True,exist_ok=True)
                temporary=path.with_suffix('.'+uuid.uuid4().hex+'.tmp')
                try:temporary.write_text(json.dumps({'recipes':recipes},ensure_ascii=False),encoding='utf-8');temporary.replace(path)
                except OSError:pass
            return recipes,hit,''
        except Exception as exc:
            if len(batches)==1:raise
            return [],hit,'、'.join(names or ['未分段配图'])+'：'+(str(exc) if isinstance(exc,ValueError) else '整理请求失败，重试可补齐。')
    results=[None]*len(batches)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        pending={pool.submit(copy_context().run,process,batch):index for index,batch in enumerate(batches)}
        completed=0
        for future in as_completed(pending):
            index=pending[future]
            result=future.result()
            results[index]=result
            completed+=1
            if on_batch is not None:
                on_batch(index,result[0],batches[index][0],completed,len(batches),result[2])
    recipes=[row for rows,_,_ in results for row in rows]
    return recipes,{'recipeRoute':'parallel' if len(batches)>1 else 'whole','recipeCacheHit':all(hit for _,hit,error in results) and not any(error for _,_,error in results),'recipeGroups':len(batches),'recipeRequests':sum(not hit for _,hit,_ in results),'recipeFailedGroups':sum(bool(error) for _,_,error in results)},[error for _,_,error in results if error]
