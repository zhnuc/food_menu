"""Production ASGI entry point. Domain rules stay independent of HTTP."""
import asyncio
import json
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from accounts import Accounts, AccountError
from pipeline import parse
from recipes import shopping
import ai
from job_service import Jobs

ROOT = Path(__file__).resolve().parent
COOKIE = 'together_session'


def create_app(database=None):
    @asynccontextmanager
    async def lifespan(app):
        app.state.accounts = await run_in_threadpool(Accounts, database or os.getenv('DATABASE_URL') or os.getenv('ACCOUNT_DB', str(ROOT/'.data/accounts.sqlite3')))
        try:
            yield
        finally:
            app.state.accounts.database.close()

    app = FastAPI(title='一起吃饭', version='0.4.0', lifespan=lifespan)

    @app.exception_handler(AccountError)
    async def account_error(request, exc):
        return JSONResponse({'error':str(exc)}, status_code=exc.status, headers={'Cache-Control':'no-store'})

    @app.exception_handler(ValueError)
    async def input_error(request, exc):
        return JSONResponse({'error':'输入数据不正确'}, status_code=400)

    @app.middleware('http')
    async def guard(request, call_next):
        if request.url.path.startswith('/api/') and request.method not in ('GET','HEAD','OPTIONS'):
            origin = request.headers.get('origin')
            allowed = set(filter(None, os.getenv('APP_ALLOWED_ORIGINS','').split(',')))
            own = f'{request.url.scheme}://{request.headers.get("host", "")}'
            if origin and origin != own and origin not in allowed or request.headers.get('sec-fetch-site') == 'cross-site' and origin not in allowed:
                return JSONResponse({'error':'请从应用页面发起操作'}, status_code=403)
            maximum = 12_500_000
            total = 0
            chunks = []
            async for chunk in request.stream():
                total += len(chunk)
                if total > maximum:
                    return JSONResponse({'error':'输入内容过长'}, status_code=413)
                chunks.append(chunk)
            request._body = b''.join(chunks)
        response = await call_next(request)
        response.headers['X-Content-Type-Options']='nosniff'
        if request.url.path.startswith('/api/'):
            response.headers['Cache-Control']='no-store'
        return response

    async def payload(request):
        if not request.headers.get('content-type','').startswith('application/json'):
            raise AccountError('请使用JSON请求',415)
        value = await request.json()
        if not isinstance(value,dict):
            raise AccountError('输入必须是JSON对象')
        return value

    async def current(request):
        return await run_in_threadpool(request.app.state.accounts.current, request.cookies.get(COOKIE,''))

    @app.get('/api/health')
    async def health(request:Request):
        with request.app.state.accounts.connect() as db:
            db.execute('SELECT 1').fetchone()
        import time
        marker=Path(os.getenv('WORKER_HEARTBEAT',ROOT/'.data/worker-heartbeat'))
        return {'ok':True,'database':'postgresql' if request.app.state.accounts.database.postgres else 'sqlite','version':'0.4.0',
                'workerActive':marker.exists() and time.time()-marker.stat().st_mtime<60}

    @app.get('/api/status')
    def status():
        return {'model':ai.settings()[2],'visionModel':ai.settings('vision')[2],
                'recipeModel':ai.settings('recipe')[2],'configured':bool(ai.settings()[0]),'platforms':['xiaohongshu','bilibili','douyin']}

    @app.post('/api/jobs')
    async def create_job(request:Request):
        body=await payload(request)
        return await run_in_threadpool(Jobs(request.app.state.accounts).create,request.cookies.get(COOKIE,''),body)

    @app.get('/api/jobs')
    async def list_jobs(request:Request):
        return {'jobs':await run_in_threadpool(Jobs(request.app.state.accounts).list,request.cookies.get(COOKIE,''))}

    @app.get('/api/jobs/{identity}')
    async def get_job(identity:str,request:Request,after:int=0):
        return await run_in_threadpool(Jobs(request.app.state.accounts).get,request.cookies.get(COOKIE,''),identity,after)

    @app.post('/api/jobs/{identity}/{action}')
    async def job_action(identity:str,action:str,request:Request):
        return await run_in_threadpool(Jobs(request.app.state.accounts).action,request.cookies.get(COOKIE,''),identity,action)

    @app.get('/media/{folder}/{name}')
    async def media(folder:str,name:str,request:Request):
        asset=f'/media/{folder}/{name}'
        if not re.fullmatch(r'/media/[a-f0-9]{24}/(?:frame-\d+\.jpg|image-\d+\.(?:jpg|png|webp)|video\.mp4)',asset):
            raise AccountError('材料不存在',404)
        store=request.app.state.accounts
        def resolve():
            with store.connect() as db:
                user=store.user(db,request.cookies.get(COOKIE,''))
                if not db.execute('SELECT 1 FROM media_grants WHERE household_id=? AND asset=?',(user['household'],asset)).fetchone():
                    raise AccountError('材料不存在',404)
            path=ROOT/'data'/folder/name
            if not path.is_file():raise AccountError('材料不存在',404)
            return path
        return FileResponse(await run_in_threadpool(resolve),headers={'Cache-Control':'private, no-store'})

    @app.post('/api/files')
    async def upload(request:Request,purpose:str='cover'):
        store=request.app.state.accounts
        raw=await request.body()
        def save():
            with store.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                user=store.user(db,request.cookies.get(COOKIE,''))
                return {'url':store.files.put(db,user,raw,purpose)}
        return await run_in_threadpool(save)

    @app.get('/api/files/{identity}')
    async def file(identity:str,request:Request):
        store=request.app.state.accounts
        def resolve():
            with store.connect() as db:
                user=store.user(db,request.cookies.get(COOKIE,''))
                return store.files.authorize(db,user,identity)[0]
        path=await run_in_threadpool(resolve)
        return FileResponse(path,media_type='image/jpeg',headers={'Cache-Control':'private, no-store'})

    @app.get('/api/account/session')
    async def session(request:Request):
        try:
            data=await current(request)
            if request.query_params.get('revision')==str(data['revision']) and request.query_params.get('household')==data['household']['id']:
                data.pop('snapshot',None)
            return data
        except AccountError as exc:
            if exc.status != 401: raise
            return {'user':None}

    @app.post('/api/account/{action}')
    async def account(action:str, request:Request):
        store=request.app.state.accounts
        body=await payload(request)
        token=request.cookies.get(COOKIE,'')
        if action in ('register','login'):
            if token:
                try: await current(request)
                except AccountError as exc:
                    if exc.status != 401: raise
                else: raise AccountError('请先退出当前账号')
            token=await run_in_threadpool(getattr(store,action),body,request.client.host if request.client else 'local')
            data=await run_in_threadpool(store.current,token)
        elif action=='logout':
            await run_in_threadpool(store.logout,token)
            token='';data={'user':None}
        elif action=='profile':
            return await run_in_threadpool(store.profile,token,body)
        else: raise AccountError('接口不存在',404)
        response=JSONResponse(data)
        response.set_cookie(COOKIE, token, max_age=30*86400 if token else 0,
            httponly=True, secure=os.getenv('ACCOUNT_SECURE_COOKIE')=='1', samesite='strict')
        return response

    @app.post('/api/household/{action}')
    async def household(action:str,request:Request):
        store=request.app.state.accounts;body=await payload(request);token=request.cookies.get(COOKIE,'')
        if action=='join':
            user=await current(request)
            await run_in_threadpool(store.throttle,'join:'+user['user']['id'])
        method={'join':store.join,'commands':store.command,'save':store.save}.get(action)
        if not method: raise AccountError('接口不存在',404)
        return await run_in_threadpool(method,token,body)

    @app.post('/api/shopping')
    async def shopping_list(request:Request):
        await current(request)
        return {'items':shopping((await payload(request)).get('recipes',[]))}

    @app.post('/api/parse')
    async def parse_link(request:Request):
        if os.getenv('ALLOW_INLINE_PARSE','0')!='1':
            await current(request)
            raise AccountError('请通过菜谱生成任务提交，处理进度会保存在服务器',410)
        if os.getenv('ALLOW_GUEST_PARSE','0')!='1':
            await current(request)
        body=await payload(request)
        if 'application/x-ndjson' not in request.headers.get('accept',''):
            return await run_in_threadpool(parse,body)
        async def stream():
            loop=asyncio.get_running_loop();queue=asyncio.Queue()
            def emit(kind,data):
                loop.call_soon_threadsafe(queue.put_nowait,{'type':kind,**data})
            def execute():
                try:
                    result=parse(body,on_event=emit)
                    emit('done',{'recipeCount':len(result['recipes']),'warnings':result['warnings'],'timings':result['timings']})
                except Exception:
                    emit('error',{'error':'生成中断，已生成的菜谱保留，请重试'})
                finally: loop.call_soon_threadsafe(queue.put_nowait,None)
            worker=asyncio.create_task(run_in_threadpool(execute))
            try:
                while True:
                    event=await queue.get()
                    if event is None:break
                    yield json.dumps(event,ensure_ascii=False)+'\n'
            finally:
                await worker
        return StreamingResponse(stream(),media_type='application/x-ndjson',headers={'X-Accel-Buffering':'no'})

    app.mount('/',StaticFiles(directory=ROOT/'web',html=True),name='web')
    return app


app=create_app()
