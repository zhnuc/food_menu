"""Account HTTP routes with cookie sessions and same-origin JSON writes."""
import json
import os
from http.cookies import SimpleCookie
from urllib.parse import urlsplit, parse_qs
from accounts import Accounts, AccountError


class AccountRoutes:
    def account_store(self):
        if not hasattr(self.server, 'accounts'):
            self.server.accounts = Accounts(os.getenv('ACCOUNT_DB', str(self.account_root / '.data/accounts.sqlite3')))
        return self.server.accounts

    def account_token(self):
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get('Cookie', ''))
            return cookie['together_session'].value if 'together_session' in cookie else ''
        except Exception:
            return ''

    def account_respond(self, data, status=200, token=None):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        if token is not None:
            secure = '; Secure' if os.getenv('ACCOUNT_SECURE_COOKIE') == '1' else ''
            age = 30*86400 if token else 0
            self.send_header('Set-Cookie', f'together_session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age={age}{secure}')
        self.end_headers()
        self.wfile.write(body)

    def account_route(self, method):
        path = urlsplit(self.path).path
        if not path.startswith(('/api/account/', '/api/household/')):
            return False
        try:
            store, token = self.account_store(), self.account_token()
            if method == 'GET' and path == '/api/account/session':
                try:
                    data = store.current(token)
                    query = parse_qs(urlsplit(self.path).query)
                    if query.get('revision') == [str(data['revision'])] and query.get('household') == [data['household']['id']]:
                        data.pop('snapshot', None)
                except AccountError as exc:
                    if exc.status != 401: raise
                    data = {'user': None}
                self.account_respond(data)
                return True
            if method != 'POST':
                raise AccountError('接口不存在', 404)
            origin = self.headers.get('Origin')
            if (origin and urlsplit(origin).netloc != self.headers.get('Host')) or self.headers.get('Sec-Fetch-Site') == 'cross-site':
                raise AccountError('请从应用页面发起操作', 403)
            if not self.headers.get('Content-Type', '').startswith('application/json'):
                raise AccountError('请使用JSON请求', 415)
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 12_500_000:
                raise AccountError('输入内容过长', 413)
            payload = json.loads(self.rfile.read(size))
            if not isinstance(payload, dict):
                raise AccountError('输入必须是JSON对象')
            if path in ('/api/account/register', '/api/account/login'):
                if token:
                    try:
                        store.current(token)
                    except AccountError:
                        pass
                    else:
                        raise AccountError('请先退出当前账号')
                peer = self.client_address[0]
                token = store.register(payload, peer) if path.endswith('/register') else store.login(payload, peer)
                self.account_respond(store.current(token), token=token)
            elif path == '/api/account/logout':
                store.logout(token)
                self.account_respond({'user': None}, token='')
            elif path == '/api/account/profile':
                self.account_respond(store.profile(token, payload))
            elif path == '/api/household/join':
                store.throttle('join:'+store.current(token)['user']['id'])
                self.account_respond(store.join(token, payload))
            elif path == '/api/household/save':
                self.account_respond(store.save(token, payload))
            elif path == '/api/household/commands':
                self.account_respond(store.command(token, payload))
            else:
                raise AccountError('接口不存在', 404)
        except AccountError as exc:
            self.account_respond({'error': str(exc)}, exc.status)
        except (ValueError, TypeError, KeyError):
            self.account_respond({'error': '输入数据不正确'}, 400)
        except Exception:
            self.account_respond({'error': '账号服务暂时不可用，请重试'}, 500)
        return True
