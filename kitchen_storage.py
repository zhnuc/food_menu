"""Versioned entity storage. Existing household snapshots remain migration backups.

SQLite is the first adapter; the domain commands do not depend on SQLite. The
next infrastructure milestone migrates these entities and receipts to PostgreSQL.
"""
import json


def encode(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':'))


ENTITY_TABLES = {'spaces': 'kitchen_spaces', 'stocks': 'kitchen_stocks',
                 'operations': 'kitchen_operations', 'records': 'kitchen_records',
                 'recipes': 'kitchen_recipes'}


def initialize(db):
    for table in ENTITY_TABLES.values():
        db.execute(f'''CREATE TABLE IF NOT EXISTS {table} (
            household_id TEXT NOT NULL REFERENCES households(id), id TEXT NOT NULL,
            position INTEGER NOT NULL, data TEXT NOT NULL,
            PRIMARY KEY(household_id,id))''')
    db.executescript('''
        CREATE TABLE IF NOT EXISTS kitchen_meta (
            household_id TEXT PRIMARY KEY REFERENCES households(id),
            schema_version INTEGER NOT NULL, current_meal_id TEXT NOT NULL,
            recipe_meta TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS kitchen_meals (
            household_id TEXT NOT NULL REFERENCES households(id), id TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('draft','locked','cooking','done','cancelled')),
            data TEXT NOT NULL, PRIMARY KEY(household_id,id));
        CREATE TABLE IF NOT EXISTS kitchen_evidence (
            household_id TEXT NOT NULL REFERENCES households(id), id TEXT NOT NULL,
            data TEXT NOT NULL, PRIMARY KEY(household_id,id));
        CREATE TABLE IF NOT EXISTS kitchen_allocations (
            household_id TEXT NOT NULL, operation_id TEXT NOT NULL,
            position INTEGER NOT NULL, stock_id TEXT NOT NULL,
            quantity REAL NOT NULL CHECK(quantity > 0),
            PRIMARY KEY(household_id,operation_id,position),
            FOREIGN KEY(household_id,operation_id) REFERENCES kitchen_operations(household_id,id),
            FOREIGN KEY(household_id,stock_id) REFERENCES kitchen_stocks(household_id,id));
        CREATE TABLE IF NOT EXISTS kitchen_commands (
            household_id TEXT NOT NULL REFERENCES households(id), id TEXT NOT NULL,
            actor_id TEXT NOT NULL REFERENCES users(id), kind TEXT NOT NULL,
            request_hash TEXT NOT NULL, revision INTEGER NOT NULL,
            result TEXT NOT NULL, created_at REAL NOT NULL,
            PRIMARY KEY(household_id,id));
        CREATE INDEX IF NOT EXISTS kitchen_commands_actor ON kitchen_commands(actor_id,created_at);
    ''')


def exists(db, household):
    return db.execute('SELECT 1 FROM kitchen_meta WHERE household_id=?', (household,)).fetchone() is not None


def write(db, household, bundle):
    state, recipe_data = bundle['state'], bundle['recipeData']
    old_allocations = {}
    for allocation in db.execute('SELECT * FROM kitchen_allocations WHERE household_id=? ORDER BY position', (household,)):
        old_allocations.setdefault(allocation['operation_id'], []).append({'stockId':allocation['stock_id'],'quantity':allocation['quantity']})
    new_ops = {op['id']:op for op in state['operations']}
    for identity, rows in old_allocations.items():
        if identity not in new_ops or rows != new_ops[identity]['allocations']:
            db.execute('DELETE FROM kitchen_allocations WHERE household_id=? AND operation_id=?', (household, identity))
    for key, table in ENTITY_TABLES.items():
        previous = {row['id']:row for row in db.execute(f'SELECT * FROM {table} WHERE household_id=?', (household,))}
        rows = recipe_data['recipes'] if key == 'recipes' else state[key]
        identities = {row['id'] for row in rows}
        for identity in previous.keys()-identities:
            db.execute(f'DELETE FROM {table} WHERE household_id=? AND id=?', (household, identity))
        for position, row in enumerate(rows):
            data = {k: v for k, v in row.items() if k != 'allocations'} if key == 'operations' else row
            encoded = encode(data)
            old = previous.get(row['id'])
            if old is None or old['data'] != encoded or old['position'] != position:
                db.execute(f'INSERT INTO {table}(household_id,id,position,data) VALUES (?,?,?,?) ON CONFLICT(household_id,id) DO UPDATE SET position=excluded.position,data=excluded.data', (household, row['id'], position, encoded))
    for op in state['operations']:
        if old_allocations.get(op['id'], []) == op['allocations']:
            continue
        for position, allocation in enumerate(op['allocations']):
            db.execute('INSERT INTO kitchen_allocations VALUES (?,?,?,?,?)',
                       (household, op['id'], position, allocation['stockId'], allocation['quantity']))
    meal = state['meal']
    db.execute('INSERT INTO kitchen_meals VALUES (?,?,?,?) ON CONFLICT(household_id,id) DO UPDATE SET status=excluded.status,data=excluded.data',
               (household, meal['id'], meal['status'], encode(meal)))
    recipe_meta = {k: v for k, v in recipe_data.items() if k not in ('recipes', 'evidence')}
    db.execute('INSERT INTO kitchen_meta VALUES (?,1,?,?) ON CONFLICT(household_id) DO UPDATE SET current_meal_id=excluded.current_meal_id,recipe_meta=excluded.recipe_meta',
               (household, meal['id'], encode(recipe_meta)))
    old_evidence = {row['id']:row['data'] for row in db.execute('SELECT * FROM kitchen_evidence WHERE household_id=?', (household,))}
    for identity in old_evidence.keys()-recipe_data.get('evidence', {}).keys():
        db.execute('DELETE FROM kitchen_evidence WHERE household_id=? AND id=?', (household, identity))
    for identity, row in recipe_data.get('evidence', {}).items():
        encoded=encode(row)
        if old_evidence.get(identity) != encoded:
            db.execute('INSERT INTO kitchen_evidence VALUES (?,?,?) ON CONFLICT(household_id,id) DO UPDATE SET data=excluded.data', (household, identity, encoded))


def read(db, household):
    meta = db.execute('SELECT * FROM kitchen_meta WHERE household_id=?', (household,)).fetchone()
    state, recipe_data = {'version': 1}, json.loads(meta['recipe_meta'])
    for key, table in ENTITY_TABLES.items():
        rows = [json.loads(row['data']) for row in db.execute(f'SELECT data FROM {table} WHERE household_id=? ORDER BY position', (household,))]
        if key == 'recipes':
            recipe_data['recipes'] = rows
        else:
            state[key] = rows
    allocations = {}
    for row in db.execute('SELECT * FROM kitchen_allocations WHERE household_id=? ORDER BY position', (household,)):
        allocations.setdefault(row['operation_id'], []).append({'stockId': row['stock_id'], 'quantity': row['quantity']})
    for op in state['operations']:
        op['allocations'] = allocations.get(op['id'], [])
    state['meal'] = json.loads(db.execute('SELECT data FROM kitchen_meals WHERE household_id=? AND id=?', (household, meta['current_meal_id'])).fetchone()['data'])
    recipe_data['evidence'] = {row['id']: json.loads(row['data']) for row in db.execute('SELECT * FROM kitchen_evidence WHERE household_id=?', (household,))}
    return {'state': state, 'recipeData': recipe_data}
