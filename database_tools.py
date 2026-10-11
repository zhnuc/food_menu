"""Private portable backups and transactional restore into an empty database."""
import argparse
import json
import os
import re
import zipfile
from pathlib import Path
from accounts import Accounts
import kitchen_storage

TABLES=['households','users','sessions','attempts','kitchen_files','kitchen_spaces','kitchen_stocks',
        'kitchen_meals','kitchen_meta','kitchen_evidence','kitchen_operations',
        'kitchen_allocations','kitchen_records','kitchen_recipes','kitchen_commands',
        'ai_jobs','ai_job_events','ai_usage','media_grants']


def backup(store,path):
    payload={'format':'together-private-backup','version':2,'tables':{}}
    with store.connect() as db:
        db.execute('BEGIN')
        for table in TABLES:
            rows=[dict(row) for row in db.execute('SELECT * FROM '+table)]
            # PostgreSQL has a generated quantity column; canonical data is in JSON.
            if table=='kitchen_stocks':
                for row in rows:row.pop('quantity',None)
            payload['tables'][table]=rows
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():raise ValueError('备份文件已存在，请换一个文件名')
    try:
        with zipfile.ZipFile(path,'x',compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('database.json',json.dumps(payload,ensure_ascii=False,allow_nan=False))
            for row in payload['tables']['kitchen_files']:
                identity=row['id']
                if not re.fullmatch('[a-f0-9]{32}',identity):raise ValueError('图片元数据无效')
                archive.write(store.files.root/(identity+'.jpg'),'files/'+identity+'.jpg')
    except BaseException:
        path.unlink(missing_ok=True);raise
    try:path.chmod(0o600)
    except OSError:pass


def restore(store,path):
    path=Path(path)
    archive=zipfile.ZipFile(path) if zipfile.is_zipfile(path) else None
    try:
        if archive:
            if archive.getinfo('database.json').file_size>100_000_000:raise ValueError('备份元数据过大')
            data=json.loads(archive.read('database.json'))
        else:data=json.loads(path.read_text(encoding='utf-8'))
        _restore(store,data,archive)
    finally:
        if archive:archive.close()


def _restore(store,data,archive):
    if data.get('format')!='together-private-backup' or data.get('version') not in (1,2) or set(data.get('tables',{}))!=set(TABLES):
        raise ValueError('备份格式不正确')
    if data['version']==2 and archive is None:raise ValueError('文件备份缺失')
    created=[]
    try:
      with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        if store.database.postgres:
            db.execute('SELECT pg_advisory_xact_lock(741208130)')
        for table in TABLES:
            if db.execute('SELECT 1 FROM '+table+' LIMIT 1').fetchone():raise ValueError('恢复目标必须为空，原数据库未修改')
        for table in TABLES:
            # Column whitelist comes from the destination, not the backup file.
            cursor=db.execute('SELECT * FROM '+table+' LIMIT 0')
            columns=[column[0] for column in cursor.description if not(table=='kitchen_stocks' and column[0]=='quantity')]
            for row in data['tables'][table]:
                if not isinstance(row,dict) or set(row)!=set(columns):raise ValueError('备份字段不正确')
                db.execute(f'INSERT INTO {table}({",".join(columns)}) VALUES ({",".join("?" for _ in columns)})',[row[key] for key in columns])
        for row in db.execute('SELECT id FROM households').fetchall():
            Accounts.snapshot(kitchen_storage.read(db,row['id']))
        for row in data['tables']['kitchen_files']:
            identity=row['id']
            if not archive or not re.fullmatch('[a-f0-9]{32}',identity):raise ValueError('图片备份缺失')
            item=archive.getinfo('files/'+identity+'.jpg')
            if item.file_size!=row['size'] or item.file_size>8_000_000:raise ValueError('图片备份尺寸不一致')
            raw=archive.read(item)
            target=store.files.root/(identity+'.jpg')
            if target.exists():
                if target.read_bytes()!=raw:raise ValueError('目标目录存在不同的同名图片')
            else:
                with target.open('xb') as file:file.write(raw)
                created.append(target)
    except BaseException:
        for item in created:item.unlink(missing_ok=True)
        raise


def main():
    parser=argparse.ArgumentParser(description='账号、家庭私有备份；包含密码散列和会话，请勿公开')
    parser.add_argument('action',choices=['backup','restore','import-sqlite'])
    parser.add_argument('file',type=Path)
    args=parser.parse_args()
    target=os.getenv('DATABASE_URL') or os.getenv('ACCOUNT_DB','.data/accounts.sqlite3')
    store=Accounts(target)
    try:
        if args.action=='backup':backup(store,args.file)
        elif args.action=='restore':restore(store,args.file)
        else:
            import sqlite3,tempfile
            if not args.file.is_file():raise ValueError('找不到 SQLite 来源')
            with tempfile.TemporaryDirectory(prefix='kitchen-import-') as tmp:
                copy=Path(tmp)/'source.sqlite3'
                with sqlite3.connect(args.file) as source,sqlite3.connect(copy) as dest:source.backup(dest)
                old=Accounts(copy)
                try:
                    archive=Path(tmp)/'private.json';backup(old,archive);restore(store,archive)
                finally:old.database.close()
        print('Database operation completed; no secrets printed')
    finally:store.database.close()


if __name__=='__main__':main()
