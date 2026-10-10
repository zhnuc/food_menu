"""Local account sessions and household snapshots, independent of model services."""
import base64
import hashlib
import hmac
import json
import re
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path


class AccountError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


class Accounts:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS households (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, invite TEXT UNIQUE NOT NULL,
                    snapshot TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1);
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY, login TEXT UNIQUE NOT NULL, nickname TEXT NOT NULL,
                    password TEXT NOT NULL, avatar TEXT NOT NULL DEFAULT '',
                    household TEXT NOT NULL REFERENCES households(id));
                CREATE TABLE IF NOT EXISTS sessions (
                    token TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS attempts (
                    key TEXT PRIMARY KEY, count INTEGER NOT NULL, since REAL NOT NULL);
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def password_hash(password, salt=None):
        salt = salt or secrets.token_hex(16)
        digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=2**17,
                                r=8, p=1, maxmem=256*1024*1024).hex()
        return salt + ':' + digest

    @staticmethod
    def token_hash(token):
        return hashlib.sha256(token.encode()).hexdigest()

    @staticmethod
    def nickname(value):
        if not isinstance(value, str) or not 1 <= len(value.strip()) <= 30:
            raise AccountError('昵称请填写1到30个字')
        return value.strip()

    @staticmethod
    def avatar(value):
        if not isinstance(value, str) or len(value) > 300000:
            raise AccountError('头像过大，请重新选择')
        if value:
            if not re.fullmatch(r'data:image/(?:jpeg|png|webp);base64,[A-Za-z0-9+/]+=*', value):
                raise AccountError('请选择有效的头像图片')
            try:
                raw = base64.b64decode(value.split(',', 1)[1], validate=True)
            except ValueError:
                raise AccountError('请选择有效的头像图片')
            if not (raw.startswith(b'\xff\xd8\xff') or raw.startswith(b'\x89PNG\r\n\x1a\n') or
                    raw.startswith(b'RIFF') and raw[8:12] == b'WEBP'):
                raise AccountError('请选择有效的头像图片')
        return value

    @staticmethod
    def snapshot(value):
        if not isinstance(value, dict) or not isinstance(value.get('state'), dict) or not isinstance(value.get('recipeData'), dict):
            raise AccountError('厨房数据格式不正确')
        state = value['state']
        if state.get('version') != 1 or any(not isinstance(state.get(key), list) for key in ('stocks', 'spaces', 'records', 'operations')):
            raise AccountError('厨房数据格式不正确')
        meal = state.get('meal')
        if not isinstance(meal, dict) or meal.get('status') not in ('draft', 'locked', 'cooking', 'done', 'cancelled'):
            raise AccountError('餐次数据格式不正确')
        if any(not isinstance(meal.get(key), list) for key in ('selections', 'dishes', 'needs')):
            raise AccountError('餐次数据格式不正确')
        if not isinstance(value['recipeData'].get('recipes'), list):
            raise AccountError('菜谱数据格式不正确')
        if not isinstance(meal.get('id'), str) or not meal['id']:
            raise AccountError('餐次数据格式不正确')
        spaces = {}
        for row in state['spaces']:
            if (not isinstance(row, dict) or not isinstance(row.get('id'), str) or row['id'] in spaces or
                    not isinstance(row.get('name'), str) or not row['name'].strip() or
                    row.get('layout') not in ('four', 'two', 'horizontal') or
                    not isinstance(row.get('zones'), list) or len(row['zones']) != (4 if row['layout']=='four' else 2) or
                    any(not isinstance(zone, str) for zone in row['zones'])):
                raise AccountError('储物空间数据不正确')
            spaces[row['id']] = row
        ids = set()
        for row in state['stocks']:
            if (not isinstance(row, dict) or not isinstance(row.get('id'), str) or row['id'] in ids or
                    not isinstance(row.get('name'), str) or not isinstance(row.get('unit'), str) or
                    type(row.get('quantity')) not in (int, float) or row['quantity'] < 0 or
                    type(row.get('zone')) is not int or row['zone'] < 0 or
                    row.get('space') is not None and (row['space'] not in spaces or row['zone'] >= len(spaces[row['space']]['zones']))):
                raise AccountError('食材库存数据不正确')
            ids.add(row['id'])
        shared = {key: state[key] for key in ('version', 'stocks', 'spaces', 'records', 'operations', 'meal')}
        encoded = json.dumps({'state': shared, 'recipeData': value['recipeData']}, ensure_ascii=False, allow_nan=False)
        if len(encoded.encode()) > 12_000_000:
            raise AccountError('家庭数据过大，请先导出照片或菜谱备份')
        return encoded

    def throttle(self, key):
        now = time.time()
        with self.connect() as db:
            row = db.execute('SELECT * FROM attempts WHERE key=?', (key,)).fetchone()
            if row and now-row['since'] < 900 and row['count'] >= 15:
                raise AccountError('尝试次数较多，请15分钟后再试', 429)
            if not row or now-row['since'] >= 900:
                db.execute('INSERT OR REPLACE INTO attempts VALUES (?,1,?)', (key, now))
            else:
                db.execute('UPDATE attempts SET count=count+1 WHERE key=?', (key,))

    def session(self, db, user_id):
        token = secrets.token_urlsafe(32)
        db.execute('DELETE FROM sessions WHERE expires<?', (time.time(),))
        db.execute('INSERT INTO sessions VALUES (?,?,?)', (self.token_hash(token), user_id, time.time()+30*86400))
        return token

    def register(self, payload, peer):
        login = payload.get('login', '')
        password = payload.get('password', '')
        if not isinstance(login, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{3,40}', login):
            raise AccountError('账号用3到40位字母、数字、下划线或短横线')
        if not isinstance(password, str) or not 8 <= len(password) <= 128:
            raise AccountError('密码请填写8到128位字符')
        nickname = self.nickname(payload.get('nickname', ''))
        snapshot = self.snapshot(payload.get('snapshot'))
        self.throttle('register:'+peer)
        encoded = self.password_hash(password)
        user, household = secrets.token_hex(16), secrets.token_hex(16)
        with self.connect() as db:
            try:
                db.execute('INSERT INTO households VALUES (?,?,?,?,1)',
                           (household, nickname+'的小厨房', secrets.token_hex(6).upper(), snapshot))
                db.execute('INSERT INTO users VALUES (?,?,?,?,?,?)', (user, login.lower(), nickname, encoded, '', household))
                token = self.session(db, user)
            except sqlite3.IntegrityError:
                raise AccountError('这个账号已经注册了')
        return token

    def login(self, payload, peer):
        login, password = payload.get('login', ''), payload.get('password', '')
        if not isinstance(login, str) or not isinstance(password, str) or len(login)>40 or len(password)>128:
            raise AccountError('账号或密码不正确', 401)
        key = 'login:'+peer+':'+login.lower()
        self.throttle('login-peer:'+peer)
        self.throttle(key)
        with self.connect() as db:
            user = db.execute('SELECT * FROM users WHERE login=?', (login.lower(),)).fetchone()
            salt = user['password'].split(':')[0] if user else '0'*32
            digest = self.password_hash(password, salt)
            if not user or not hmac.compare_digest(digest, user['password']):
                raise AccountError('账号或密码不正确', 401)
            db.execute('DELETE FROM attempts WHERE key=?', (key,))
            return self.session(db, user['id'])

    def user(self, db, token):
        row = db.execute('SELECT users.* FROM users JOIN sessions ON users.id=sessions.user_id '
                         'WHERE sessions.token=? AND sessions.expires>?', (self.token_hash(token), time.time())).fetchone()
        if not row:
            raise AccountError('请先登录账号', 401)
        return row

    @staticmethod
    def public(user):
        return {key: user[key] for key in ('id', 'login', 'nickname', 'avatar')}

    def current(self, token):
        with self.connect() as db:
            user = self.user(db, token)
            household = db.execute('SELECT * FROM households WHERE id=?', (user['household'],)).fetchone()
            members = db.execute('SELECT * FROM users WHERE household=? ORDER BY rowid', (household['id'],)).fetchall()
            return {'user': self.public(user), 'household': {key: household[key] for key in ('id', 'name', 'invite')},
                    'members': [self.public(row) for row in members], 'revision': household['revision'],
                    'snapshot': json.loads(household['snapshot'])}

    def logout(self, token):
        with self.connect() as db:
            db.execute('DELETE FROM sessions WHERE token=?', (self.token_hash(token),))

    def profile(self, token, payload):
        nickname, avatar = self.nickname(payload.get('nickname')), self.avatar(payload.get('avatar', ''))
        with self.connect() as db:
            user = self.user(db, token)
            db.execute('UPDATE users SET nickname=?,avatar=? WHERE id=?', (nickname, avatar, user['id']))
        return self.current(token)

    def join(self, token, payload):
        code = payload.get('code', '')
        if not isinstance(code, str):
            raise AccountError('请填写家庭邀请码')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            user = self.user(db, token)
            household = db.execute('SELECT id FROM households WHERE invite=?', (code.strip().upper(),)).fetchone()
            if not household:
                raise AccountError('邀请码不存在，请向家人确认')
            db.execute('UPDATE users SET household=? WHERE id=?', (household['id'], user['id']))
        return self.current(token)

    def save(self, token, payload):
        encoded = self.snapshot(payload.get('snapshot'))
        revision = payload.get('revision')
        if type(revision) is not int:
            raise AccountError('厨房数据版本不正确')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            user = self.user(db, token)
            old = db.execute('SELECT snapshot,revision FROM households WHERE id=?', (user['household'],)).fetchone()
            if old['revision'] != revision:
                raise AccountError('家人刚更新了厨房，已刷新，请重新操作', 409)
            previous = json.loads(old['snapshot'])['state']['meal']
            current = json.loads(encoded)['state']['meal']
            if previous['id'] == current['id'] and previous['status'] != 'draft' and (
                    previous['selections'] != current['selections'] or previous['dishes'] != current['dishes']):
                raise AccountError('本餐菜单已固定，暂无法点菜', 409)
            if previous['id'] != current['id'] and previous['status'] not in ('done', 'cancelled'):
                raise AccountError('请先完成或取消当前这餐', 409)
            allowed = {'draft': ('draft','locked','cancelled'), 'locked': ('locked','cooking','cancelled'),
                       'cooking': ('cooking','done','cancelled'), 'done': ('done',), 'cancelled': ('cancelled',)}
            if previous['id'] == current['id'] and current['status'] not in allowed[previous['status']]:
                raise AccountError('餐次状态已变化，请刷新后重试', 409)
            db.execute('UPDATE households SET snapshot=?,revision=revision+1 WHERE id=?', (encoded, user['household']))
        return {'revision': revision+1}
