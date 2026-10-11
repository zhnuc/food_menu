"""Opt-in domain suite on separate PostgreSQL databases, never a user DB."""
import os
import re
import tempfile
import uuid
from unittest.mock import patch
import unittest
from accounts import Accounts
import test_kitchen_service as kitchen_tests
import test_jobs as job_tests


def isolated_store(case):
    import psycopg
    from psycopg import sql
    from urllib.parse import urlsplit,urlunsplit
    admin=os.environ['TEST_POSTGRES_URL'];name='food_menu_test_'+uuid.uuid4().hex
    with psycopg.connect(admin,autocommit=True) as db:db.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
    parts=urlsplit(admin);target=urlunsplit((parts.scheme,parts.netloc,'/'+name,parts.query,''));store=Accounts(target)
    def cleanup():
        store.database.close()
        with psycopg.connect(admin,autocommit=True) as db:db.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
    case.addCleanup(cleanup)
    return store


@unittest.skipUnless(os.getenv('TEST_POSTGRES_URL'), 'Set TEST_POSTGRES_URL to an isolated PostgreSQL admin database')
class PostgresKitchenTests(kitchen_tests.KitchenTests):
    def setUp(self):
        import psycopg
        from psycopg import sql
        from psycopg.conninfo import conninfo_to_dict, make_conninfo
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.password=patch.object(Accounts,'password_hash',staticmethod(lambda password,salt=None:'0'*32+':test'))
        self.password.start();self.addCleanup(self.password.stop)
        admin=os.environ['TEST_POSTGRES_URL'];name='food_menu_test_'+uuid.uuid4().hex
        with psycopg.connect(admin,autocommit=True) as db:db.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
        config=conninfo_to_dict(admin);config['dbname']=name
        # Accounts selects adapter from a URL; quote only the generated test name.
        from urllib.parse import urlsplit,urlunsplit
        parts=urlsplit(admin);self.path=urlunsplit((parts.scheme,parts.netloc,'/'+name,parts.query,''))
        self.store=Accounts(self.path)
        def clean():
            self.store.database.close()
            with psycopg.connect(admin,autocommit=True) as db:
                db.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
        self.addCleanup(clean)
        self.addCleanup(self.store.database.close)
        from test_kitchen_service import bundle
        self.token=self.store.register({'login':'alice','password':'password123','nickname':'小禾','snapshot':bundle()},'test')


@unittest.skipUnless(os.getenv('TEST_POSTGRES_URL'),'Set TEST_POSTGRES_URL for queue and restore checks')
class PostgresJobTests(job_tests.JobTests):
    def setUp(self):
        super().setUp()
        self.store=isolated_store(self)
        self.token=self.store.register({'login':'alice','nickname':'禾','password':'password123','snapshot':kitchen_tests.bundle()},'local')
        self.bob=self.store.register({'login':'bob','nickname':'乙','password':'password123','snapshot':kitchen_tests.bundle()},'local')
        from job_service import Jobs
        self.jobs=Jobs(self.store)

    def test_expired_lease_recovery_and_stale_worker_cannot_finish(self):
        item=self.create();first=self.jobs.claim(now=100);second=self.jobs.claim(now=200)
        self.assertFalse(self.jobs.finish(first,{'old':True}));self.assertTrue(self.jobs.finish(second,{'new':True}))
        self.assertTrue(self.jobs.get(self.token,item['id'])['result']['new'])

    def test_sqlite_to_postgres_backup_and_return_restore(self):
        from database_tools import backup,restore
        from file_storage import Files
        from job_service import Jobs
        import io
        from PIL import Image
        from pathlib import Path
        source=Accounts(Path(self.tmp.name)/'source.db');source.files=Files(Path(self.tmp.name)/'source-files')
        token=source.register({'login':'origin','nickname':'禾','password':'password123','snapshot':kitchen_tests.bundle()},'test')
        output=io.BytesIO();Image.new('RGB',(4,4),'red').save(output,format='PNG')
        with source.connect() as db:url=source.files.put(db,source.user(db,token),output.getvalue(),'avatar')
        source.profile(token,{'nickname':'备份测试','avatar':url})
        job=Jobs(source).create(token,{'requestId':'cross-db-001','kind':'text','input':{'prompt':'家常菜'}})
        archive=Path(self.tmp.name)/'to-postgres.zip';backup(source,archive)
        target=isolated_store(self);target.files=Files(Path(self.tmp.name)/'postgres-files');restore(target,archive)
        self.assertEqual(source.current(token),target.current(token));self.assertEqual(Jobs(target).get(token,job['id'])['status'],'queued')
        returned=Path(self.tmp.name)/'to-sqlite.zip';backup(target,returned)
        restored=Accounts(Path(self.tmp.name)/'returned.db');restored.files=Files(Path(self.tmp.name)/'returned-files');restore(restored,returned)
        self.assertEqual(source.current(token),restored.current(token));self.assertEqual(len(list(restored.files.root.glob('*.jpg'))),1)


if __name__=='__main__':unittest.main()
