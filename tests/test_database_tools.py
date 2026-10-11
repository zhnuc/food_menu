import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from accounts import Accounts
from database_tools import backup,restore
from test_kitchen_service import bundle


class BackupTests(unittest.TestCase):
    def test_backup_restores_private_images_and_jobs_to_a_new_directory(self):
        import io
        from PIL import Image
        from file_storage import Files
        from job_service import Jobs
        with tempfile.TemporaryDirectory() as tmp,patch.object(Accounts,'password_hash',staticmethod(lambda password,salt=None:'0'*32+':test')):
            first=Accounts(Path(tmp)/'one.db');first.files=Files(Path(tmp)/'one-files')
            token=first.register({'login':'alice','nickname':'禾','password':'password123','snapshot':bundle()},'test')
            output=io.BytesIO();Image.new('RGB',(5,5),'red').save(output,format='PNG')
            with first.connect() as db:url=first.files.put(db,first.user(db,token),output.getvalue(),'cover')
            info=first.current(token);card=info['snapshot']['recipeData']['recipes'][0];card['coverImage']=url
            first.command(token,{'id':'with-photo-001','revision':info['revision'],'role':'chef','kind':'recipe.upsert','payload':{'recipe':card,'evidence':{}}})
            job=Jobs(first).create(token,{'requestId':'backup-job-001','kind':'text','input':{'prompt':'测试菜'}})
            path=Path(tmp)/'private.zip';backup(first,path)
            second=Accounts(Path(tmp)/'two.db');second.files=Files(Path(tmp)/'two-files');restore(second,path)
            self.assertEqual(first.current(token),second.current(token))
            self.assertEqual(Jobs(second).get(token,job['id'])['status'],'queued')
            with second.connect() as db:restored,_=second.files.authorize(db,second.user(db,token),url.split('/')[-1])
            self.assertEqual(restored.read_bytes(),(first.files.root/restored.name).read_bytes())

    def test_backup_restore_retains_accounts_receipts_and_live_reservations(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(Accounts,'password_hash',staticmethod(lambda password,salt=None:'0'*32+':test')):
            first=Accounts(Path(tmp)/'one.db');token=first.register({'login':'alice','nickname':'禾','password':'password123','snapshot':bundle()},'test')
            for kind,payload in [('meal.pick',{'recipeId':'pepper'}),('meal.lock',{})]:
                info=first.current(token);first.command(token,{'id':'command-'+kind,'revision':info['revision'],'role':'chef','mealId':'meal-one','kind':kind,'payload':payload})
            info=first.current(token);need=info['snapshot']['state']['meal']['needs'][0]['id']
            command={'id':'backup-prepare','revision':info['revision'],'role':'chef','mealId':'meal-one','kind':'meal.prepare','payload':{'direction':'left','needId':need,'quantity':300}}
            first.command(token,command)
            path=Path(tmp)/'private.json';backup(first,path)
            second=Accounts(Path(tmp)/'two.db');restore(second,path)
            self.assertEqual(first.current(token),second.current(token))
            self.assertTrue(second.command(token,command)['duplicate'])
            with self.assertRaises(ValueError):restore(second,path)
            self.assertEqual(first.current(token),second.current(token))

    def test_invalid_backup_rolls_back_all_tables(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=Accounts(Path(tmp)/'empty.db');path=Path(tmp)/'bad.json'
            from database_tools import TABLES
            data={'format':'together-private-backup','version':1,'tables':{key:[] for key in TABLES}}
            data['tables']['households']=[{'id':'bad','name':'家','invite':'CODE','snapshot':'{}','revision':1}]
            data['tables']['users']=[{'unrecognized':'field'}]
            path.write_text(json.dumps(data),encoding='utf-8')
            with self.assertRaises(ValueError):restore(store,path)
            with store.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM households').fetchone()[0],0)
