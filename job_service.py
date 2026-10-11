"""Database queue with bounded inputs, leases, durable events and household access."""
import hashlib
import json
import os
import re
import time
import uuid
from accounts import AccountError


def encoded(value):
    return json.dumps(value,ensure_ascii=False,allow_nan=False,separators=(',',':'))


def initialize(db):
    db.executescript('''
        CREATE TABLE IF NOT EXISTS ai_jobs (
            id TEXT PRIMARY KEY, household_id TEXT NOT NULL REFERENCES households(id),
            user_id TEXT NOT NULL REFERENCES users(id), request_id TEXT NOT NULL,
            fingerprint TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL,
            status TEXT NOT NULL, attempts INTEGER NOT NULL, lease TEXT NOT NULL,
            lease_until REAL NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL,
            result TEXT NOT NULL, error TEXT NOT NULL,
            UNIQUE(user_id,request_id));
        CREATE TABLE IF NOT EXISTS ai_job_events (
            job_id TEXT NOT NULL REFERENCES ai_jobs(id), sequence INTEGER NOT NULL,
            event TEXT NOT NULL, PRIMARY KEY(job_id,sequence));
        CREATE TABLE IF NOT EXISTS ai_usage (
            id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES ai_jobs(id),
            model TEXT NOT NULL, succeeded INTEGER NOT NULL,
            input_tokens INTEGER, output_tokens INTEGER, elapsed REAL NOT NULL,
            created_at REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS media_grants (
            household_id TEXT NOT NULL REFERENCES households(id), asset TEXT NOT NULL,
            created_at REAL NOT NULL, PRIMARY KEY(household_id,asset));
    ''')
    db.execute('CREATE INDEX IF NOT EXISTS ai_jobs_queue ON ai_jobs(status,lease_until,created_at)')
    db.execute('CREATE INDEX IF NOT EXISTS ai_jobs_user_created ON ai_jobs(user_id,created_at)')
    db.execute('CREATE INDEX IF NOT EXISTS ai_jobs_household_created ON ai_jobs(household_id,created_at)')


class Jobs:
    def __init__(self,store):self.store=store

    @staticmethod
    def validate(body):
        kind=body.get('kind','link');payload=body.get('input',{})
        request_id=body.get('requestId')
        if not isinstance(request_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,100}',request_id):
            raise AccountError('任务编号无效')
        if kind not in ('link','text','image','ingredients') or not isinstance(payload,dict):
            raise AccountError('请选择链接、图片或文字生成方式')
        if len(encoded(payload).encode())>100_000:raise AccountError('输入内容过长')
        keys={'link':{'share','article','subtitle','video_ocr','image_ocr'},
              'text':{'prompt'},'image':{'image','prompt'},'ingredients':{'ingredients','prompt'}}[kind]
        if set(payload)-keys or any(not isinstance(value,str) or len(value)>30_000 for value in payload.values()):
            raise AccountError('任务输入格式不正确')
        if kind=='link' and not any(value.strip() for value in payload.values()):raise AccountError('请填写链接或来源正文')
        if kind=='text' and not payload.get('prompt','').strip():raise AccountError('请描述想做的菜')
        if kind=='ingredients' and not payload.get('ingredients','').strip():raise AccountError('请填写已有食材')
        if kind=='image' and not re.fullmatch(r'/api/files/[a-f0-9]{32}',payload.get('image','')):
            raise AccountError('请先上传菜谱图片')
        return kind,payload,request_id

    def create(self,token,body):
        kind,payload,request_id=self.validate(body)
        fingerprint=hashlib.sha256(encoded([kind,payload]).encode()).hexdigest();now=time.time()
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE');user=self.store.user(db,token)
            self.store.database.lock_user(db,user['id'])
            prior=db.execute('SELECT * FROM ai_jobs WHERE user_id=? AND request_id=?',(user['id'],request_id)).fetchone()
            if prior:
                if prior['fingerprint']!=fingerprint:raise AccountError('任务编号已用于其他输入',409)
                if prior['household_id']!=user['household']:raise AccountError('请在原家庭查看此任务',409)
                return self.view(db,prior)
            if kind=='image':
                _,file=self.store.files.authorize(db,user,payload['image'].split('/')[-1])
                if file['purpose']!='recipe-input':raise AccountError('请选择菜谱识别图片')
            pending=db.execute("SELECT COUNT(*) FROM ai_jobs WHERE user_id=? AND status IN ('queued','running')",(user['id'],)).fetchone()[0]
            daily=db.execute('SELECT COUNT(*) FROM ai_jobs WHERE user_id=? AND created_at>?',(user['id'],now-86400)).fetchone()[0]
            if pending>=int(os.getenv('AI_MAX_PENDING','3')):raise AccountError('正在处理的任务较多，请稍后再提交',429)
            if daily>=int(os.getenv('AI_DAILY_TASKS','30')):raise AccountError('今天的生成额度已用完，请明天再试',429)
            identity=uuid.uuid4().hex
            db.execute('INSERT INTO ai_jobs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (identity,user['household'],user['id'],request_id,fingerprint,kind,encoded(payload),'queued',0,'',0,now,now,'{}',''))
            return self.view(db,db.execute('SELECT * FROM ai_jobs WHERE id=?',(identity,)).fetchone())

    @staticmethod
    def view(db,row,after=0):
        return {'id':row['id'],'kind':row['kind'],'status':row['status'],'attempts':row['attempts'],
                'createdAt':row['created_at'],'updatedAt':row['updated_at'],'result':json.loads(row['result']),
                'error':row['error'],'events':[{'sequence':event['sequence'],**json.loads(event['event'])}
                    for event in db.execute('SELECT * FROM ai_job_events WHERE job_id=? AND sequence>? ORDER BY sequence',(row['id'],after))]}

    def owned(self,db,token,identity):
        user=self.store.user(db,token)
        row=db.execute('SELECT * FROM ai_jobs WHERE id=? AND household_id=?',(identity,user['household'])).fetchone()
        if not row:raise AccountError('任务不存在',404)
        return row

    def get(self,token,identity,after=0):
        with self.store.connect() as db:
            db.execute('BEGIN');return self.view(db,self.owned(db,token,identity),max(0,after))

    def list(self,token):
        with self.store.connect() as db:
            user=self.store.user(db,token)
            rows=db.execute('SELECT * FROM ai_jobs WHERE household_id=? ORDER BY created_at DESC LIMIT 30',(user['household'],)).fetchall()
            return [{'id':row['id'],'kind':row['kind'],'status':row['status'],'createdAt':row['created_at'],'error':row['error']} for row in rows]

    def action(self,token,identity,action):
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE');row=self.owned(db,token,identity)
            self.store.database.lock_household(db,row['household_id'])
            # Re-read after the lock on PostgreSQL (another request may have completed).
            row=self.owned(db,token,identity)
            if action=='cancel':
                db.execute("UPDATE ai_jobs SET status='cancelled',lease='',lease_until=0,updated_at=? WHERE id=? AND status IN ('queued','running')",(time.time(),identity))
            elif action=='retry':
                if row['status']!='failed':raise AccountError('只有失败任务可以重试',409)
                if row['attempts']>=int(os.getenv('AI_MAX_ATTEMPTS','3')):raise AccountError('已达到重试次数，请核对输入后重新提交',429)
                # Existing partial results are retained until a new attempt completes.
                db.execute("UPDATE ai_jobs SET status='queued',error='',lease='',lease_until=0,updated_at=? WHERE id=?",(time.time(),identity))
            else:raise AccountError('任务操作不存在',404)
            return self.view(db,self.owned(db,token,identity))

    def claim(self,now=None):
        now=time.time() if now is None else now;maximum=int(os.getenv('AI_MAX_ATTEMPTS','3'))
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute("UPDATE ai_jobs SET status='failed',error='处理多次中断，请核对输入后重新提交',lease='' WHERE status='running' AND lease_until<? AND attempts>=?",(now,maximum))
            suffix=' FOR UPDATE SKIP LOCKED' if self.store.database.postgres else ''
            row=db.execute("SELECT * FROM ai_jobs WHERE attempts<? AND (status='queued' OR (status='running' AND lease_until<?)) ORDER BY created_at LIMIT 1"+suffix,(maximum,now)).fetchone()
            if not row:return None
            lease=uuid.uuid4().hex
            db.execute("UPDATE ai_jobs SET status='running',attempts=attempts+1,lease=?,lease_until=?,updated_at=? WHERE id=?",(lease,now+90,now,row['id']))
            return {**dict(row),'lease':lease,'payload':json.loads(row['payload'])}

    def heartbeat(self,job):
        with self.store.connect() as db:
            return db.execute("UPDATE ai_jobs SET lease_until=? WHERE id=? AND lease=? AND status='running'",(time.time()+90,job['id'],job['lease'])).rowcount==1

    def emit(self,job,kind,data):
        event={'type':kind,**data}
        if len(encoded(event).encode())>2_000_000:raise ValueError('任务结果过大')
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if self.store.database.postgres:
                row=db.execute('SELECT * FROM ai_jobs WHERE id=? FOR UPDATE',(job['id'],)).fetchone()
            else:row=db.execute('SELECT * FROM ai_jobs WHERE id=?',(job['id'],)).fetchone()
            if row['status']!='running' or row['lease']!=job['lease']:return False
            count=db.execute('SELECT COALESCE(MAX(sequence),0) FROM ai_job_events WHERE job_id=?',(job['id'],)).fetchone()[0]
            if count>=500:raise ValueError('任务事件过多')
            db.execute('INSERT INTO ai_job_events VALUES (?,?,?)',(job['id'],count+1,encoded(event)))
            self.grant_media(db,job['household_id'],data)
            db.execute('UPDATE ai_jobs SET updated_at=? WHERE id=?',(time.time(),job['id']))
        return True

    @staticmethod
    def grant_media(db,household,data):
        def walk(value):
            if isinstance(value,str) and re.fullmatch(r'/media/[a-f0-9]{24}/(?:frame-\d+\.jpg|image-\d+\.(?:jpg|png|webp)|video\.mp4)',value):
                db.execute('INSERT INTO media_grants VALUES (?,?,?) ON CONFLICT(household_id,asset) DO NOTHING',(household,value,time.time()))
            elif isinstance(value,dict):
                for item in value.values():walk(item)
            elif isinstance(value,list):
                for item in value:walk(item)
        walk(data)

    def finish(self,job,result=None,error=''):
        value=encoded(result or {})
        if len(value.encode())>8_000_000:raise ValueError('任务结果过大')
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            changed=db.execute("UPDATE ai_jobs SET status=?,result=?,error=?,lease='',lease_until=0,updated_at=? WHERE id=? AND lease=? AND status='running'",
                ('failed' if error else 'succeeded',value,error,time.time(),job['id'],job['lease'])).rowcount
            if changed:self.grant_media(db,job['household_id'],result)
            return changed==1

    def usage(self,job,entry):
        with self.store.connect() as db:
            db.execute('INSERT INTO ai_usage VALUES (?,?,?,?,?,?,?,?)',(uuid.uuid4().hex,job['id'],entry['model'],int(entry['succeeded']),entry['inputTokens'],entry['outputTokens'],entry['elapsed'],time.time()))
