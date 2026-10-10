"""Serve the static mobile prototype on the LAN; no model or account APIs."""
import argparse
import json
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

WEB = Path(__file__).resolve().parent / 'web'


class PreviewHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB), **kwargs)

    def end_headers(self):
        self.send_header('Cache-Control', 'no-store')
        super().end_headers()

    def do_GET(self):
        path = (WEB / unquote(urlsplit(self.path).path).lstrip('/')).resolve()
        if not path.is_relative_to(WEB):
            self.send_error(404)
            return
        if path == WEB:
            path = WEB / 'index.html'
        if path.name in ('index.html', 'mobile.html') and path.parent == WEB:
            body = path.read_text(encoding='utf-8').replace(
                '</head>', '<script>window.STATIC_PREVIEW=true;</script></head>'
            ).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if not path.is_file():
            self.send_error(404)
            return
        super().do_GET()

    def do_POST(self):
        body = json.dumps({'error': '手机预览用于体验厨房和一餐流程。链接识别请在电脑本机页面使用。'},
                          ensure_ascii=False).encode('utf-8')
        self.send_response(501)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8770)
    args = parser.parse_args()
    print(f'手机流程预览：http://{args.host}:{args.port}/', flush=True)
    ThreadingHTTPServer((args.host, args.port), PreviewHandler).serve_forever()
