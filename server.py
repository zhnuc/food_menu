"""HTTP transport and static assets; business flow lives in pipeline.py."""
import json
import mimetypes
import os
import re
from pathlib import Path
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
import ai
from pipeline import parse
from recipes import shopping
from account_http import AccountRoutes

ROOT = Path(__file__).parent

class Handler(AccountRoutes, SimpleHTTPRequestHandler):
    account_root = ROOT
    def __init__(self,*args,**kwargs): super().__init__(*args,directory=str(ROOT/'web'),**kwargs)
    def do_GET(self):
        if self.account_route('GET'): return
        if self.path=='/api/status': return self.respond({'model':ai.settings()[2],'visionModel':ai.settings('vision')[2],'recipeModel':ai.settings('recipe')[2],'configured':bool(ai.settings()[0]),'platforms':['xiaohongshu','bilibili','douyin']})
        if self.path.startswith('/media/'):
            match=re.fullmatch(r'/media/([a-f0-9]{24})/(frame-\d+\.jpg|image-\d+\.(?:jpg|png|webp)|video\.mp4)',self.path)
            if not match:return self.respond({'error':'材料不存在'},404)
            path=ROOT/'data'/match[1]/match[2]
            if not path.is_file():return self.respond({'error':'材料不存在'},404)
            self.send_response(200);self.send_header('Content-Type',mimetypes.guess_type(path.name)[0]);self.send_header('Content-Length',str(path.stat().st_size));self.end_headers()
            with path.open('rb') as f:
                while chunk:=f.read(65536):self.wfile.write(chunk)
            return
        super().do_GET()
    def respond(self,data,status=200):
        body=json.dumps(data,ensure_ascii=False).encode(); self.send_response(status); self.send_header('Content-Type','application/json; charset=utf-8'); self.end_headers(); self.wfile.write(body)
    def stream_parse(self,payload):
        self.send_response(200)
        self.send_header('Content-Type','application/x-ndjson; charset=utf-8')
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Accel-Buffering','no')
        self.end_headers()
        def emit(kind,data):
            self.wfile.write((json.dumps({'type':kind,**data},ensure_ascii=False)+'\n').encode())
            self.wfile.flush()
        try:
            result=parse(payload,on_event=emit)
            # Cards and evidence were already sent once in earlier events.
            emit('done',{'recipeCount':len(result['recipes']),'warnings':result['warnings'],'timings':result['timings']})
        except (BrokenPipeError,ConnectionResetError):
            pass
        except Exception as exc:
            try:emit('error',{'error':str(exc) if isinstance(exc,ValueError) else '生成中断，已生成的卡片保留，可重试补齐。'})
            except (BrokenPipeError,ConnectionResetError):pass
    def do_POST(self):
        if self.account_route('POST'): return
        try:
            size=int(self.headers.get('Content-Length','0'))
            if size>200000: raise ValueError('输入内容过长')
            payload=json.loads(self.rfile.read(size))
            if not isinstance(payload,dict):raise ValueError('输入必须是JSON对象')
            if self.path=='/api/parse':
                if 'application/x-ndjson' in self.headers.get('Accept',''):
                    return self.stream_parse(payload)
                return self.respond(parse(payload))
            if self.path=='/api/shopping': return self.respond({'items':shopping(payload['recipes'])})
            self.respond({'error':'接口不存在'},404)
        except ValueError as e: self.respond({'error':str(e)},400)
        except Exception: self.respond({'error':'服务请求失败，请检查模型或媒体提取配置；原始输入仍可手动编辑。'},502)


if __name__=='__main__':
    port=int(os.getenv('PORT','8767'))
    print(f'一起吃饭：http://127.0.0.1:{port}',flush=True)
    ThreadingHTTPServer((os.getenv('HOST','127.0.0.1'),port),Handler).serve_forever()
