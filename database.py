"""SQLite development adapter and pooled PostgreSQL production adapter."""
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path


class Database:
    def __init__(self, target):
        self.target = str(target)
        self.postgres = self.target.startswith(('postgres://', 'postgresql://'))
        self.pool = None
        if self.postgres:
            from psycopg_pool import ConnectionPool
            self.pool = ConnectionPool(self.target, min_size=1, open=True,
                max_size=int(os.getenv('DB_POOL_SIZE', '8')), timeout=15,
                kwargs={'autocommit': True, 'row_factory': self.row_factory,
                        'options': '-c statement_timeout=15000 -c idle_in_transaction_session_timeout=30000'})
            self.pool.wait(timeout=20)
        else:
            Path(self.target).parent.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def row_factory(cursor):
        names = [c.name for c in cursor.description] if cursor.description else []
        class Row(dict):
            def __getitem__(self, key):
                return super().__getitem__(names[key] if isinstance(key, int) else key)
        return lambda values: Row(zip(names, values))

    @contextmanager
    def connect(self):
        if self.postgres:
            with self.pool.connection() as conn:
                db = PostgresConnection(conn)
                try:
                    conn.execute('BEGIN')
                    yield db
                    conn.commit()
                except BaseException:
                    conn.rollback()
                    raise
        else:
            conn = sqlite3.connect(self.target, timeout=15)
            conn.row_factory = sqlite3.Row
            conn.execute('PRAGMA foreign_keys=ON')
            try:
                with conn:
                    yield conn
            finally:
                conn.close()

    def lock_user(self, db, identity):
        if self.postgres:
            return db.execute('SELECT * FROM users WHERE id=? FOR UPDATE', (identity,)).fetchone()

    def lock_household(self, db, identity):
        if self.postgres:
            db.execute('SELECT id FROM households WHERE id=? FOR UPDATE', (identity,)).fetchone()

    def close(self):
        if self.pool:
            self.pool.close()


class PostgresConnection:
    def __init__(self, conn):
        self.conn = conn

    def execute(self, sql, args=()):
        # SQL is application-owned; values always use driver parameters.
        if sql.strip().upper().startswith('BEGIN'):
            if sql.strip().upper() == 'BEGIN':
                return self.conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
            return self.conn.execute('SELECT 1')
        return self.conn.execute(sql.replace('?', '%s').replace(' REAL ', ' DOUBLE PRECISION '), args)

    def executescript(self, sql):
        for statement in sql.split(';'):
            if statement.strip():
                self.execute(statement)


def integrity_errors():
    try:
        from psycopg import IntegrityError
        return (sqlite3.IntegrityError, IntegrityError)
    except ImportError:
        return (sqlite3.IntegrityError,)
