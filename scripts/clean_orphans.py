"""Remove only untracked private files, never files referenced by metadata."""
import os
import re
import time
from accounts import Accounts

store=Accounts(os.getenv('DATABASE_URL') or os.getenv('ACCOUNT_DB','.data/accounts.sqlite3'))
try:
    with store.connect() as db:known={row['id'] for row in db.execute('SELECT id FROM kitchen_files').fetchall()}
    removed=0
    for path in store.files.root.iterdir():
        if re.fullmatch('[a-f0-9]{32}\.jpg',path.name) and path.stem not in known and path.is_file() and time.time()-path.stat().st_mtime>86400:
            path.unlink();removed+=1
    print(f'Removed {removed} untracked objects older than 24 hours')
finally:store.database.close()
