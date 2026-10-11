"""Account sessions and transactional household commands, independent of AI."""
import base64
import hashlib
import hmac
import json
import re
import secrets
import time
import kitchen_service as kitchen
import kitchen_storage
from contextlib import contextmanager
from pathlib import Path
from database import Database, integrity_errors
import file_storage


class AccountError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


class Accounts:
    def __init__(self, path):
        self.path = Path(path) if not str(path).startswith(('postgres://','postgresql://')) else None
        self.database = Database(path)
        self.files = file_storage.Files()
        with self.connect() as db:
            if self.database.postgres:
                db.execute('SELECT pg_advisory_xact_lock(741208130)')
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
            kitchen_storage.initialize(db)
            file_storage.initialize(db)
            from job_service import initialize as initialize_jobs
            initialize_jobs(db)
            db.execute('BEGIN IMMEDIATE')
            for row in db.execute('SELECT id,snapshot FROM households').fetchall():
                if not kitchen_storage.exists(db, row['id']):
                    bundle = json.loads(self.snapshot(json.loads(row['snapshot'])))
                    kitchen_storage.write(db, row['id'], bundle)
            db.execute('CREATE INDEX IF NOT EXISTS users_household ON users(household,id)')
            db.execute('CREATE INDEX IF NOT EXISTS sessions_expiry ON sessions(expires)')
            db.execute('CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at REAL NOT NULL)')
            db.execute('INSERT INTO schema_migrations VALUES (1,?) ON CONFLICT(version) DO NOTHING', (time.time(),))
            if self.database.postgres:
                db.execute("CREATE INDEX IF NOT EXISTS kitchen_stocks_location ON kitchen_stocks(household_id,((data::jsonb)->>'space'))")
                db.execute("ALTER TABLE kitchen_stocks ADD COLUMN IF NOT EXISTS quantity NUMERIC GENERATED ALWAYS AS (((data::jsonb)->>'quantity')::numeric) STORED")
                db.execute('INSERT INTO schema_migrations VALUES (2,?) ON CONFLICT(version) DO NOTHING', (time.time(),))

    @contextmanager
    def connect(self):
        with self.database.connect() as db:
            yield db

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
        if re.fullmatch(r'/api/files/[a-f0-9]{32}',value):return value
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
        try:
            kitchen.validate_bundle({'state': shared, 'recipeData': value['recipeData']})
        except (kitchen.KitchenError, KeyError, TypeError, ValueError) as exc:
            raise AccountError(str(exc) if isinstance(exc, kitchen.KitchenError) else '家庭数据格式不正确')
        try:
            encoded = json.dumps({'state': shared, 'recipeData': value['recipeData']}, ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError):
            raise AccountError('家庭数据格式不正确')
        if len(encoded.encode()) > 12_000_000:
            raise AccountError('家庭数据过大，请先导出照片或菜谱备份')
        return encoded

    def throttle(self, key):
        now = time.time()
        with self.connect() as db:
            row = db.execute('''INSERT INTO attempts VALUES (?,1,?) ON CONFLICT(key) DO UPDATE SET
                count=CASE WHEN ?-attempts.since>=900 THEN 1 ELSE attempts.count+1 END,
                since=CASE WHEN ?-attempts.since>=900 THEN excluded.since ELSE attempts.since END
                RETURNING count,since''', (key,now,now,now)).fetchone()
            if row['count'] > 15:
                raise AccountError('尝试次数较多，请15分钟后再试', 429)

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
                bundle=json.loads(snapshot)
                self.files.migrate_bundle(db,{'id':user,'household':household},bundle)
                kitchen_storage.write(db, household, bundle)
                token = self.session(db, user)
            except integrity_errors():
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
            db.execute('BEGIN')
            user = self.user(db, token)
            return self.current_in_transaction(db, user)

    def current_in_transaction(self, db, user):
        household = db.execute('SELECT * FROM households WHERE id=?', (user['household'],)).fetchone()
        members = db.execute('SELECT * FROM users WHERE household=? ORDER BY id', (household['id'],)).fetchall()
        return {'user': self.public(user), 'household': {key: household[key] for key in ('id', 'name', 'invite')},
                'members': [self.public(row) for row in members], 'revision': household['revision'],
                'snapshot': kitchen_storage.read(db, household['id']), 'schemaVersion': 1}

    def logout(self, token):
        with self.connect() as db:
            db.execute('DELETE FROM sessions WHERE token=?', (self.token_hash(token),))

    def profile(self, token, payload):
        nickname, avatar = self.nickname(payload.get('nickname')), self.avatar(payload.get('avatar', ''))
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            user = self.user(db, token)
            avatar=self.files.externalize(db,user,avatar,'avatar')
            db.execute('UPDATE users SET nickname=?,avatar=? WHERE id=?', (nickname, avatar, user['id']))
        return self.current(token)

    def join(self, token, payload):
        code = payload.get('code', '')
        if not isinstance(code, str):
            raise AccountError('请填写家庭邀请码')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            user = self.user(db, token)
            if self.database.postgres:
                user = self.database.lock_user(db, user['id'])
            household = db.execute('SELECT id FROM households WHERE invite=?', (code.strip().upper(),)).fetchone()
            if not household:
                raise AccountError('邀请码不存在，请向家人确认')
            db.execute('UPDATE users SET household=? WHERE id=?', (household['id'], user['id']))
        return self.current(token)

    def save(self, token, payload):
        with self.connect() as db:
            self.user(db, token)
        raise AccountError('整份覆盖接口已停用，请刷新页面后通过具体操作保存', 410)

    def command(self, token, payload):
        identity = payload.get('id')
        kind, arguments, role = payload.get('kind'), payload.get('payload', {}), payload.get('role')
        if not isinstance(identity, str) or not 8 <= len(identity) <= 120 or not isinstance(kind, str) or not isinstance(arguments, dict):
            raise AccountError('操作格式不正确')
        revision = payload.get('revision')
        if type(revision) is not int or revision < 1:
            raise AccountError('厨房数据版本不正确')
        try:
            request_hash = hashlib.sha256(kitchen_storage.encode({'kind': kind, 'payload': arguments,
                'role': role, 'mealId': payload.get('mealId')}).encode()).hexdigest()
        except (TypeError, ValueError):
            raise AccountError('操作格式不正确')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            user = self.user(db, token)
            if self.database.postgres:
                user = self.database.lock_user(db, user['id'])
            household = user['household']
            self.database.lock_household(db, household)
            previous = db.execute('SELECT * FROM kitchen_commands WHERE household_id=? AND id=?', (household, identity)).fetchone()
            if previous:
                if previous['actor_id'] != user['id'] or previous['request_hash'] != request_hash:
                    raise AccountError('操作编号已被其他请求使用', 409)
                result, duplicate = json.loads(previous['result']), True
            else:
                old = db.execute('SELECT revision FROM households WHERE id=?', (household,)).fetchone()
                if old['revision'] != revision:
                    raise AccountError('家人刚更新了厨房，请刷新后重新操作', 409)
                bundle = kitchen_storage.read(db, household)
                try:
                    result = kitchen.apply(bundle, kind, arguments, role, payload.get('mealId'))
                    self.snapshot(bundle)
                    self.files.migrate_bundle(db,user,bundle)
                except kitchen.KitchenError as exc:
                    raise AccountError(str(exc), exc.status)
                kitchen_storage.write(db, household, bundle)
                db.execute('UPDATE households SET revision=revision+1 WHERE id=?', (household,))
                db.execute('INSERT INTO kitchen_commands VALUES (?,?,?,?,?,?,?,?)',
                           (household, identity, user['id'], kind, request_hash, revision+1,
                            kitchen_storage.encode(result), time.time()))
                duplicate = False
            response = {**self.current_in_transaction(db, user), 'result': result, 'duplicate': duplicate}
        return response
