const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const C=require('../web/kitchen-core.js');
const initial=()=>({user:{id:'one',nickname:'禾',avatar:''},household:{id:'home',name:'家',invite:'CODE'},members:[],revision:1,snapshot:{state:{version:1},recipeData:{recipes:[]}}});
async function clientFor(responder) {
  const applied=[],notifications=[],storage=new Map();
  const sandbox={KitchenCore:C,window:{},document:{hidden:false,addEventListener(){},getElementById(){return {open:false};}},setInterval(){},localStorage:{setItem:(key,value)=>storage.set(key,value),removeItem:key=>storage.delete(key)},fetch:async(path,options)=>{
    const result=await responder(path,options);return {ok:!result.status || result.status<400,status:result.status || 200,json:async()=>result.data};
  }};
  vm.runInNewContext(fs.readFileSync(require.resolve('../web/accounts-client.js'),'utf8'),sandbox);
  const client=sandbox.window.AccountClient;
  await client.start({apply:data=>applied.push(C.clone(data)),render(){},guest(){},notify:message=>notifications.push(message)});
  return {client,applied,notifications,storage};
}
async function drained(client) {for(let i=0;i<100;i++){if(!client.syncing)return;await new Promise(resolve=>setImmediate(resolve));}throw Error('sync did not finish');}

test('household writes serialize with successive server revisions',async()=>{
  const writes=[],data=initial();
  const {client}=await clientFor((path,options)=>{if(path.includes('/save')){const payload=JSON.parse(options.body);writes.push(payload);return {data:{revision:payload.revision+1}};}return {data};});
  client.commit({state:{version:1,value:'first'},recipeData:{recipes:[]}});client.commit({state:{version:1,value:'second'},recipeData:{recipes:[]}});await drained(client);
  assert.deepEqual(writes.map(row=>row.revision),[1,2]);assert.equal(writes[1].snapshot.state.value,'second');assert.equal(client.revision,3);
});

test('conflicting update keeps a recovery backup and replaces stale state with the family version',async()=>{
  let reads=0;const newer={...initial(),revision:2,snapshot:{state:{version:1,value:'family'},recipeData:{recipes:[]}}};
  const {client,applied,notifications,storage}=await clientFor(path=>path.includes('/save')?{status:409,data:{error:'家人刚更新了厨房，已刷新，请重新操作'}}:{data:reads++?newer:initial()});
  client.commit({state:{version:1,value:'local'},recipeData:{recipes:[]}});await drained(client);
  assert.equal(client.revision,2);assert.equal(applied.at(-1).state.value,'family');assert.equal(JSON.parse(storage.get('together-unsaved-one')).state.value,'local');assert.match(notifications[0],/家人刚更新/);
});

test('profile update applies a newer kitchen snapshot and logout clears that account cache',async()=>{
  const newer={...initial(),revision:2,snapshot:{state:{version:1,value:'newer'},recipeData:{recipes:[]}}};
  const {client,applied,storage}=await clientFor(path=>({data:path.includes('/profile')?newer:path.includes('/logout')?{user:null}:initial()}));
  await client.profile({nickname:'新名字',avatar:''});assert.equal(applied.at(-1).state.value,'newer');
  storage.set('together-account-cache-one','private');await client.logout();assert.equal(client.user,null);assert.equal(storage.has('together-account-cache-one'),false);
});

test('a slow refresh cannot overwrite a newer completed save',async()=>{
  let release;
  const {client,applied}=await clientFor(path=>path.includes('?revision=')?new Promise(resolve=>{release=()=>resolve({data:initial()});}):path.includes('/save')?{data:{revision:2}}:{data:initial()});
  const pending=client.refresh();client.commit({state:{version:1,value:'saved'},recipeData:{recipes:[]}});await drained(client);
  release();await pending;assert.equal(client.revision,2);assert.equal(applied.length,1);
});
