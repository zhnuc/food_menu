const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const C=require('../web/kitchen-core.js');
const initial=()=>({user:{id:'one',nickname:'禾',avatar:''},household:{id:'home',name:'家',invite:'CODE'},members:[],revision:1,snapshot:{state:{version:1},recipeData:{recipes:[]}}});
async function clientFor(responder,storage=new Map(),cache) {
  const applied=[],notifications=[];
  const sandbox={KitchenCore:C,window:{LocalCache:cache},document:{hidden:false,addEventListener(){},getElementById(){return {open:false};}},setInterval(){},localStorage:{getItem:key=>storage.get(key)||null,setItem:(key,value)=>storage.set(key,value),removeItem:key=>storage.delete(key)},fetch:async(path,options)=>{
    const result=await responder(path,options);return {ok:!result.status || result.status<400,status:result.status || 200,json:async()=>result.data};
  }};
  vm.runInNewContext(fs.readFileSync(require.resolve('../web/accounts-client.js'),'utf8'),sandbox);
  const client=sandbox.window.AccountClient;
  await client.start({apply:data=>applied.push(C.clone(data)),render(){},guest(){},notify:message=>notifications.push(message)});
  return {client,applied,notifications,storage};
}
const context={role:'chef',mealId:'meal-one'};

test('offline startup restores a read-only copy and reconnect verifies the server session',async()=>{
  let disconnected=true,writes=0;
  const cache={restoreAccount:async()=>initial(),saveAccount:async()=>{},forgetAccount:async()=>{}};
  const {client,applied}=await clientFor((path,options)=>{if(options.method==='POST')writes++;if(disconnected)throw Error('offline');return {data:initial()};},new Map(),cache);
  assert.equal(client.offline,true);assert.equal(client.user.id,'one');assert.equal(applied.length,1);
  await assert.rejects(client.command('stock.add',{name:'鸡蛋',quantity:1},context),/当前离线/);assert.equal(writes,0);
  disconnected=false;await client.refresh();assert.equal(client.offline,false);assert.equal(client.available,true);
});

test('commands send intentions and apply the authoritative server result',async()=>{
  let sent;
  const {client,applied,storage}=await clientFor((path,options)=>{
    if(path.endsWith('/commands')){sent=JSON.parse(options.body);return {data:{...initial(),revision:2,result:{id:'server-stock'},snapshot:{state:{value:'server'},recipeData:{recipes:[]}}}};}
    return {data:initial()};
  });
  const result=await client.command('stock.add',{name:'鸡蛋',quantity:2},context);
  assert.equal(sent.kind,'stock.add');assert.equal(sent.revision,1);assert.equal(sent.snapshot,undefined);assert.equal(result.id,'server-stock');
  assert.equal(applied.at(-1).state.value,'server');assert.equal(client.revision,2);assert.equal(storage.has('together-pending-one'),false);
});

test('a lost response retries the same id instead of applying inventory twice',async()=>{
  const writes=[];
  const {client}=await clientFor((path,options)=>{
    if(path.endsWith('/commands')){writes.push(JSON.parse(options.body));if(writes.length===1)throw Error('connection lost');return {data:{...initial(),revision:2,result:{id:'one-operation'}}};}
    return {data:initial()};
  });
  await client.command('meal.prepare',{quantity:300},context);
  assert.equal(writes.length,2);assert.deepEqual(writes[0],writes[1]);assert.equal(client.revision,2);
});

test('unconfirmed write survives reload, blocks new writes and resumes under the same household',async()=>{
  let original;const storage=new Map();
  const {client}=await clientFor((path,options)=>{if(path.endsWith('/commands')){original=JSON.parse(options.body);throw Error('offline');}return {data:initial()};},storage);
  await assert.rejects(client.command('stock.add',{quantity:500},context));
  assert.equal(client.pending,true);await assert.rejects(client.command('stock.add',{quantity:500},context),/尚未确认/);
  let retried;
  const resumed=await clientFor((path,options)=>{if(path.endsWith('/commands')){retried=JSON.parse(options.body);return {data:{...initial(),revision:2,result:null}};}return {data:initial()};},storage);
  assert.deepEqual(retried,original);assert.equal(resumed.client.pending,false);assert.equal(storage.has('together-pending-one'),false);
});

test('a conflicting command refreshes state and does not queue a stale replay',async()=>{
  let reads=0;const newer={...initial(),revision:2,snapshot:{state:{value:'family'},recipeData:{recipes:[]}}};
  const {client,applied,storage}=await clientFor(path=>path.endsWith('/commands')?{status:409,data:{error:'家人刚更新了厨房'}}:{data:reads++?newer:initial()});
  await assert.rejects(client.command('stock.add',{quantity:2},context),/家人刚更新/);
  assert.equal(client.revision,2);assert.equal(applied.at(-1).state.value,'family');assert.equal(storage.has('together-pending-one'),false);
});

test('a slow refresh cannot overwrite a completed command and concurrent clicks are blocked',async()=>{
  let release,commit;
  const {client,applied}=await clientFor(path=>path.includes('?revision=')?new Promise(resolve=>{release=()=>resolve({data:initial()});}):path.endsWith('/commands')?new Promise(resolve=>{commit=()=>resolve({data:{...initial(),revision:2}});}):{data:initial()});
  const refresh=client.refresh(),pending=client.command('stock.add',{quantity:1},context);
  await assert.rejects(client.command('stock.add',{quantity:1},context),/正在保存/);
  commit();await pending;release();await refresh;
  assert.equal(client.revision,2);assert.equal(applied.length,2);
});

test('profile and logout keep account caches separate and never replay another household receipt',async()=>{
  const storage=new Map([['together-pending-one',JSON.stringify({id:'old-request',household:'other-home'})]]);
  const newer={...initial(),revision:2,snapshot:{state:{value:'newer'},recipeData:{recipes:[]}}};
  const {client,applied}=await clientFor(path=>({data:path.includes('/profile')?newer:path.includes('/logout')?{user:null}:initial()}),storage);
  assert.equal(client.pending,false);
  await client.profile({nickname:'新名字',avatar:''});assert.equal(applied.at(-1).state.value,'newer');
  storage.set('together-account-cache-one','private');await client.logout();assert.equal(client.user,null);assert.equal(storage.has('together-account-cache-one'),false);
});
