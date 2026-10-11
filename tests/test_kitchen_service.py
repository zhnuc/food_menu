"""PRD accounting and multi-account commands against real transactional storage."""
import copy
import json
import tempfile
import threading
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
from accounts import Accounts, AccountError
from kitchen_service import available, remaining


def bundle(quantity=500):
    return {'state': {'version': 1,
        'spaces': [{'id':'fridge','name':'冰箱','type':'fridge','layout':'four','zones':['左上','右上','左下','右下']}],
        'stocks': [{'id':'pork','name':'猪肉','quantity':quantity,'unit':'克','space':'fridge','zone':0}],
        'operations': [], 'records': [],
        'meal': {'id':'meal-one','status':'draft','selections':[],'dishes':[],'needs':[]}},
        'recipeData': {'version':2, 'evidence':{}, 'recipes':[
            {'id':'pepper','name':'青椒炒肉','servings':1,
             'ingredients':[{'name':'猪肉','quantity':300,'unit':'克'},{'name':'盐','quantity':None,'unit':'','pending':True}],
             'steps':['炒熟'], 'evidenceIds':[]}]}}


class KitchenTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=Path(self.tmp.name)/'accounts.db'
        self.password=patch.object(Accounts,'password_hash',staticmethod(lambda password,salt=None:'0'*32+':test'))
        self.password.start();self.addCleanup(self.password.stop);self.addCleanup(self.tmp.cleanup)
        self.store=Accounts(self.path)
        self.token=self.store.register({'login':'alice','password':'password123','nickname':'小禾','snapshot':bundle()},'test')

    def current(self, token=None):
        return self.store.current(token or self.token)

    def command(self, kind, payload=None, token=None, **extra):
        current=self.current(token)
        return self.store.command(token or self.token, {'id':str(uuid.uuid4()),'revision':current['revision'],
            'kind':kind,'payload':payload or {},'role':'chef','mealId':current['snapshot']['state']['meal']['id'],**extra})

    def lock(self):
        self.command('meal.pick',{'recipeId':'pepper','selected':True});self.command('meal.lock')
        return self.current()['snapshot']['state']['meal']['needs'][0]['id']

    def state(self):
        return self.current()['snapshot']['state']

    def prepare(self, need, direction, quantity, unit='克', **kwargs):
        return self.command('meal.prepare',{'needId':need,'direction':direction,'quantity':quantity,'unit':unit,**kwargs})['result']

    def test_left_then_finish_consumes_once_and_uses_server_time(self):
        need=self.lock();self.prepare(need,'left',300)
        state=self.state();self.assertEqual(state['stocks'][0]['quantity'],500);self.assertEqual(available(state,state['stocks'][0]),200)
        self.command('meal.begin');record=self.command('meal.finish')['result'];self.command('meal.finish')
        self.assertEqual(self.state()['stocks'][0]['quantity'],200);self.assertEqual(len(self.state()['records']),1)
        self.assertIn('+00:00',record['at']);self.assertIn('盐',record['unrecorded'])

    def test_right_does_not_use_existing_inventory(self):
        need=self.lock();self.prepare(need,'right',500)
        state=self.state();self.assertEqual(state['stocks'][0]['quantity'],1000);self.assertEqual(available(state,state['stocks'][0]),700)
        self.command('meal.begin');self.command('meal.finish');self.assertEqual(self.state()['stocks'][0]['quantity'],700)

    def test_malformed_command_fields_are_rejected_without_writes(self):
        need=self.lock();before=self.current()
        for ids in ([{}], [['pork']], ['pork','pork']):
            with self.assertRaises(AccountError):self.prepare(need,'left',100,stockIds=ids)
            self.assertEqual(self.current(),before)
        with self.assertRaises(AccountError):self.command('space.update',{'spaceId':'fridge','layout':{},'zones':[]})
        self.assertEqual(self.current(),before)

    def test_partial_left_and_repeated_right(self):
        self.command('stock.reduce',{'stockId':'pork','quantity':500});need=self.lock()
        self.prepare(need,'right',200);self.assertEqual(remaining(self.state(),self.state()['meal']['needs'][0]),100)
        self.prepare(need,'right',500);self.command('meal.begin');self.command('meal.finish')
        self.assertEqual(self.state()['stocks'][0]['quantity'],400)

    def test_invalid_quantities_and_overuse_rollback_everything(self):
        need=self.lock();before=self.current()
        for value in (0,-1,True,'NaN','Infinity',301):
            with self.assertRaises(AccountError):self.prepare(need,'left',value)
            self.assertEqual(self.current(),before)
        with self.assertRaises(AccountError):self.prepare(need,'right',1,'个')
        self.assertEqual(self.current(),before)

    def test_reduce_cannot_consume_reserved_inventory(self):
        need=self.lock();self.prepare(need,'left',300)
        with self.assertRaises(AccountError):self.command('stock.reduce',{'stockId':'pork','quantity':201})
        self.command('stock.reduce',{'stockId':'pork','quantity':100});self.command('meal.begin');self.command('meal.finish')
        self.assertEqual(self.state()['stocks'][0]['quantity'],100)

    def test_unknown_needs_never_guess_consumption(self):
        self.lock();salt=self.state()['meal']['needs'][1]['id'];self.prepare(salt,'right',100)
        self.command('meal.declare',{'needId':salt});self.command('meal.begin');self.command('meal.finish')
        self.assertEqual(next(s for s in self.state()['stocks'] if s['name']=='盐')['quantity'],100)
        self.assertEqual(self.state()['stocks'][0]['quantity'],500)

    def test_cancel_releases_reservations_and_retains_real_additions(self):
        need=self.lock();self.prepare(need,'right',500);self.command('meal.cancel');self.command('meal.new')
        self.assertEqual(self.state()['stocks'][0]['quantity'],1000);self.assertEqual(available(self.state(),self.state()['stocks'][0]),1000)

    def test_undo_right_restores_inventory_and_need(self):
        need=self.lock();op=self.prepare(need,'right',500);self.command('meal.undo',{'operationId':op['id']})
        self.assertEqual(self.state()['stocks'][0]['quantity'],500);self.assertEqual(remaining(self.state(),self.state()['meal']['needs'][0]),300)

    def test_undo_cannot_remove_inventory_used_by_later_operation(self):
        need=self.lock();op=self.prepare(need,'right',500);self.command('stock.reduce',{'stockId':'pork','quantity':700})
        with self.assertRaises(AccountError):self.command('meal.undo',{'operationId':op['id']})
        self.assertEqual(self.state()['operations'][0]['status'],'active')

    def test_edit_recipe_after_lock_keeps_fixed_dishes_and_needs(self):
        self.lock();card=copy.deepcopy(self.current()['snapshot']['recipeData']['recipes'][0]);card['ingredients'][0]['quantity']=900
        self.command('recipe.upsert',{'recipe':card})
        self.assertEqual(self.state()['meal']['needs'][0]['required'],300)
        self.assertEqual(self.state()['meal']['dishes'][0]['ingredients'][0]['quantity'],300)
        for kind,payload in [('meal.pick',{'recipeId':'pepper','selected':False}),('meal.servings',{'recipeId':'pepper','servings':2})]:
            with self.assertRaises(AccountError) as error:self.command(kind,payload)
            self.assertEqual(error.exception.status,409)

    def test_receipt_replay_after_restart_returns_same_result_at_latest_revision(self):
        need=self.lock();current=self.current();request={'id':str(uuid.uuid4()),'revision':current['revision'],'kind':'meal.prepare',
            'role':'chef','mealId':'meal-one','payload':{'needId':need,'direction':'right','quantity':500}}
        first=self.store.command(self.token,request);self.command('meal.begin');self.store=Accounts(self.path)
        replay=self.store.command(self.token,request)
        self.assertTrue(replay['duplicate']);self.assertEqual(replay['result'],first['result']);self.assertEqual(self.state()['stocks'][0]['quantity'],1000)
        self.assertEqual(replay['snapshot']['state']['meal']['status'],'cooking')
        with self.assertRaises(AccountError):self.store.command(self.token,{**request,'payload':{**request['payload'],'quantity':1}})

    def test_two_members_concurrent_requests_do_not_overwrite_or_double_prepare(self):
        bob=self.store.register({'login':'bob','password':'password123','nickname':'小满','snapshot':bundle()},'test')
        self.store.join(bob,{'code':self.current()['household']['invite']});need=self.lock();revision=self.current()['revision'];barrier=threading.Barrier(2)
        def run(token):
            barrier.wait()
            try:return self.store.command(token,{'id':str(uuid.uuid4()),'revision':revision,'kind':'meal.prepare','role':'chef','mealId':'meal-one','payload':{'needId':need,'direction':'left','quantity':300}})
            except AccountError as exc:return exc.status
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(run,[self.token,bob]))
        self.assertEqual(sum(isinstance(r,dict) for r in results),1);self.assertIn(409,results);self.assertEqual(len(self.state()['operations']),1)
        self.assertEqual(self.current(bob)['snapshot'],self.current()['snapshot'])

    def test_same_receipt_submitted_concurrently_only_increments_once(self):
        need=self.lock();current=self.current();request={'id':str(uuid.uuid4()),'revision':current['revision'],'kind':'meal.prepare','role':'chef','mealId':'meal-one','payload':{'needId':need,'direction':'right','quantity':500}}
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:self.store.command(self.token,request),range(2)))
        self.assertEqual(sorted(r['duplicate'] for r in results),[False,True]);self.assertEqual(self.current()['revision'],current['revision']+1)
        self.assertEqual(self.state()['stocks'][0]['quantity'],1000)

    def test_new_meal_rejects_stale_actions_even_with_current_revision(self):
        self.command('meal.cancel');self.command('meal.new')
        with self.assertRaises(AccountError) as error:self.command('meal.pick',{'recipeId':'pepper'},mealId='meal-one')
        self.assertEqual(error.exception.status,409)

    def test_space_delete_move_and_layout_preserve_reserved_stock(self):
        need=self.lock();self.prepare(need,'left',300)
        self.command('space.update',{'spaceId':'fridge','name':'小冰箱','layout':'two','zones':['上','下']})
        self.command('stock.move',{'stockId':'pork','space':'fridge','zone':1});self.command('space.delete',{'spaceId':'fridge'})
        self.assertIsNone(self.state()['stocks'][0]['space']);self.command('meal.begin');self.command('meal.finish')
        self.assertEqual(self.state()['stocks'][0]['quantity'],200)

    def test_family_boundary_and_no_client_snapshot_override(self):
        bob=self.store.register({'login':'bob','password':'password123','nickname':'小满','snapshot':bundle(10)},'test')
        self.command('stock.reduce',{'stockId':'pork','quantity':10,'householdId':self.current(bob)['household']['id']})
        self.assertEqual(self.current(bob)['snapshot']['state']['stocks'][0]['quantity'],10)
        with self.assertRaises(AccountError) as error:self.store.save(self.token,{'revision':self.current()['revision'],'snapshot':bundle(999)})
        self.assertEqual(error.exception.status,410)
        with self.assertRaises(AccountError):self.command('meal.finish',{},role='foodie')
        with self.assertRaises(AccountError) as error:self.store.command('invalid-token',{'id':str(uuid.uuid4()),'revision':1,'kind':'stock.add','payload':{},'role':'chef'})
        self.assertEqual(error.exception.status,401)

    def test_migration_preserves_backup_and_active_reservation_on_restart(self):
        need=self.lock();self.prepare(need,'left',300);old=self.current()['snapshot'];household=self.current()['household']['id']
        with self.store.connect() as db:
            db.execute('UPDATE households SET snapshot=? WHERE id=?',(json.dumps(old),household))
            for table in ['kitchen_allocations','kitchen_commands','kitchen_meta','kitchen_meals','kitchen_evidence','kitchen_operations','kitchen_records','kitchen_recipes','kitchen_stocks','kitchen_spaces']:
                db.execute('DELETE FROM '+table)
        self.store=Accounts(self.path);self.assertEqual(self.current()['snapshot'],old)
        self.command('meal.begin');self.command('meal.finish');self.assertEqual(self.state()['stocks'][0]['quantity'],200)
        with self.store.connect() as db:backup=json.loads(db.execute('SELECT snapshot FROM households WHERE id=?',(household,)).fetchone()[0])
        self.assertEqual(backup,old)

    def test_bad_import_does_not_create_family_or_fabricate_reservations(self):
        invalid=bundle();invalid['state']['operations']=[{'id':'fake','mealId':'meal-one','needId':'fake','type':'left','quantity':900,'status':'active','allocations':[{'stockId':'pork','quantity':900}]}]
        with self.assertRaises(AccountError):self.store.register({'login':'newbie','password':'password123','nickname':'新人','snapshot':invalid},'test')
        with self.store.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM users').fetchone()[0],1)

    def test_malformed_imported_cards_and_evidence_are_rejected(self):
        variants=[]
        bad=bundle();bad['recipeData']['recipes']=[None];variants.append(bad)
        bad=bundle();bad['recipeData']['evidence']=[];variants.append(bad)
        bad=bundle();bad['recipeData']['recipes'][0]['evidenceIds']=['missing'];variants.append(bad)
        bad=bundle();bad['recipeData']['extra']=float('nan');variants.append(bad)
        for bad in variants:
            with self.assertRaises(AccountError):Accounts.snapshot(bad)


if __name__=='__main__':unittest.main()
