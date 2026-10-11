const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const {IDBFactory}=require('fake-indexeddb');
function createCache(indexedDB=new IDBFactory(),storage=new Map()) {
  const window={indexedDB},localStorage={getItem:key=>storage.get(key)||null,setItem:(key,value)=>storage.set(key,value),removeItem:key=>storage.delete(key)};
  vm.runInNewContext(fs.readFileSync(require.resolve('../web/local-cache.js'),'utf8'),{window,localStorage,Date,Promise});
  return {cache:window.LocalCache,indexedDB,storage};
}
const account=id=>({user:{id,nickname:id},household:{id:'family-'+id},revision:2,snapshot:{state:{records:[{photo:'local-photo'}]},recipeData:{recipes:[]}}});
test('IndexedDB household copies survive client restart and stay account scoped',async()=>{
  const first=createCache();await first.cache.saveAccount(account('alice'));await first.cache.saveAccount(account('bob'));
  const restarted=createCache(first.indexedDB,first.storage);
  assert.equal((await restarted.cache.restoreAccount()).user.id,'bob');
  await restarted.cache.forgetAccount('bob');assert.equal(await restarted.cache.restoreAccount(),null);
  await restarted.cache.saveAccount(account('alice'));assert.equal((await restarted.cache.restoreAccount()).user.id,'alice');
  assert.deepEqual([...first.storage.keys()],['together-last-cached-account']);
});
test('drafts preserve input order and account clearing cannot resurrect pending writes',async()=>{
  const {cache}=createCache();
  await cache.saveDraft('alice',{steps:['第一步','第二步'],ingredients:[{name:'鸡蛋',quantity:''}]});
  assert.deepEqual(Array.from((await cache.readDraft('alice')).steps),['第一步','第二步']);
  assert.equal(await cache.readDraft('bob'),null);
  const pending=cache.saveAccount(account('alice'));const clearing=cache.forgetAccount('alice');
  await Promise.all([pending,clearing]);assert.equal(await cache.restoreAccount(),null);assert.equal(await cache.readDraft('alice'),null);
});
test('private images are account scoped and removed together with account data',async()=>{
  const {cache}=createCache();const image=new Blob(['private'],{type:'image/jpeg'});
  await cache.saveAsset('alice','/api/files/a',image);await cache.saveAsset('bob','/api/files/a',image);
  assert.equal((await cache.readAsset('alice','/api/files/a')).size,7);
  await cache.forgetAccount('alice');assert.equal(await cache.readAsset('alice','/api/files/a'),null);
  assert.equal((await cache.readAsset('bob','/api/files/a')).size,7);
});
