"""Private, household-owned image objects; metadata and business refs are separate."""
import base64
import io
import os
import re
import time
import uuid
from pathlib import Path
from PIL import Image,ImageOps,UnidentifiedImageError

ROOT=Path(__file__).resolve().parent


def initialize(db):
    db.execute('''CREATE TABLE IF NOT EXISTS kitchen_files (
        id TEXT PRIMARY KEY, household_id TEXT NOT NULL REFERENCES households(id),
        user_id TEXT NOT NULL REFERENCES users(id), purpose TEXT NOT NULL,
        size INTEGER NOT NULL, created_at REAL NOT NULL)''')
    db.execute('CREATE INDEX IF NOT EXISTS kitchen_files_household ON kitchen_files(household_id,created_at)')


class Files:
    def __init__(self,root=None):
        self.root=Path(root or os.getenv('BLOB_ROOT',ROOT/'.data/files'))
        self.root.mkdir(parents=True,exist_ok=True)

    def put(self,db,user,raw,purpose):
        from accounts import AccountError
        if purpose not in ('avatar','cover','record','recipe-input') or not raw or len(raw)>8_000_000:
            raise AccountError('请选择8MB以内的有效图片')
        try:
            with Image.open(io.BytesIO(raw)) as source:
                if source.format not in ('JPEG','PNG','WEBP') or source.width*source.height>20_000_000:
                    raise AccountError('图片尺寸或格式不支持')
                source.load();image=ImageOps.exif_transpose(source).convert('RGB')
                edge=256 if purpose=='avatar' else 1600 if purpose=='recipe-input' else 1200
                image.thumbnail((edge,edge),Image.Resampling.LANCZOS)
                output=io.BytesIO();image.save(output,format='JPEG',quality=85)
                normalized=output.getvalue()
        except (UnidentifiedImageError,OSError,Image.DecompressionBombError):
            raise AccountError('图片无法读取，请换一张')
        # Serialize quota checks with this household's uploads and business writes.
        # On SQLite the INSERT below follows the caller's write transaction.
        if hasattr(db,'conn'):
            db.execute('SELECT id FROM households WHERE id=? FOR UPDATE',(user['household'],))
        total=db.execute('SELECT COALESCE(SUM(size),0) FROM kitchen_files WHERE household_id=?',(user['household'],)).fetchone()[0]
        if total+len(normalized)>int(os.getenv('HOUSEHOLD_IMAGE_BYTES','250000000')):
            raise AccountError('家庭图片空间已用满，请联系管理员',429)
        identity=uuid.uuid4().hex
        # Random storage names; no caller path or filename becomes a disk path.
        path=self.root/(identity+'.jpg');path.write_bytes(normalized)
        try:
            db.execute('INSERT INTO kitchen_files VALUES (?,?,?,?,?,?)',(identity,user['household'],user['id'],purpose,len(normalized),time.time()))
        except BaseException:
            path.unlink(missing_ok=True);raise
        return '/api/files/'+identity

    def authorize(self,db,user,identity):
        from accounts import AccountError
        if not re.fullmatch('[a-f0-9]{32}',identity):raise AccountError('图片不存在',404)
        row=db.execute('SELECT * FROM kitchen_files WHERE id=?',(identity,)).fetchone()
        if not row:raise AccountError('图片不存在',404)
        allowed=row['household_id']==user['household'] or row['user_id']==user['id']
        if not allowed and row['purpose']=='avatar':
            member=db.execute('SELECT household FROM users WHERE id=?',(row['user_id'],)).fetchone()
            allowed=member and member['household']==user['household']
        if not allowed:raise AccountError('图片不存在',404)
        path=self.root/(identity+'.jpg')
        if not path.is_file():raise AccountError('图片不存在',404)
        return path,row

    def externalize(self,db,user,value,purpose):
        from accounts import AccountError
        if not value:return value
        if value.startswith('data:image/'):
            try:raw=base64.b64decode(value.split(',',1)[1],validate=True)
            except (ValueError,IndexError):raise AccountError('图片格式不正确')
            return self.put(db,user,raw,purpose)
        match=re.fullmatch(r'/api/files/([a-f0-9]{32})',value)
        if not match:raise AccountError('图片地址无效')
        _,row=self.authorize(db,user,match[1])
        if row['purpose']!=purpose:raise AccountError('图片用途不一致')
        return value

    def migrate_bundle(self,db,user,bundle):
        converted={}
        def walk(value):
            if isinstance(value,dict):
                for key,item in value.items():
                    if key in ('coverImage','photo') and isinstance(item,str) and item:
                        purpose='cover' if key=='coverImage' else 'record'
                        cache=(purpose,item)
                        if cache not in converted:converted[cache]=self.externalize(db,user,item,purpose)
                        value[key]=converted[cache]
                    else:walk(item)
            elif isinstance(value,list):
                for item in value:walk(item)
        walk(bundle)
