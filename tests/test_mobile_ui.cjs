/* DOM integration, not a browser-layout test. Runtime application needs no jsdom. */
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {JSDOM}=require('jsdom');
const C=require('../web/kitchen-core.js');
const html=fs.readFileSync(path.join(__dirname,'../web/index.html'),'utf8');
const KEY='together-mobile-prototype-v1';

function setup(initial,legacy,account) {
  const dom=new JSDOM(html,{url:'http://127.0.0.1:8767/',runScripts:'outside-only',pretendToBeVisual:true});
  const {window:w}=dom;w.scrollTo=()=>{};
  w.HTMLDialogElement.prototype.showModal=function(){this.setAttribute('open','');};w.HTMLDialogElement.prototype.close=function(){this.removeAttribute('open');};
  if(initial)w.localStorage.setItem(KEY,JSON.stringify({state:initial,recipeData:{version:2,recipes:initial.recipes,evidence:{}}}));
  if(legacy)w.localStorage.setItem('together-recipes',JSON.stringify(legacy));
  if(account)w.fetch=async()=>({ok:true,json:async()=>account});
  w.TextDecoder=TextDecoder;w.ReadableStream=ReadableStream;
  for(const script of w.document.querySelectorAll('script[src]'))w.eval(fs.readFileSync(path.join(__dirname,'../web',script.getAttribute('src').split('?')[0]),'utf8'));
  const find=(action,attr,value)=>[...w.document.querySelectorAll(`[data-action="${action}"]`)].find(element=>!attr || element.dataset[attr]===value);
  const click=(action,attr,value)=>{const element=find(action,attr,value);assert.ok(element,`Missing ${action} ${value || ''}`);element.click();};
  const submit=values=>{const form=w.document.querySelector('#sheet-body form');assert.ok(form);for(const [key,value] of Object.entries(values))form.elements.namedItem(key).value=String(value);form.dispatchEvent(new w.Event('submit',{bubbles:true,cancelable:true}));};
  const saved=()=>JSON.parse(w.localStorage.getItem(KEY));
  return {dom,w,find,click,submit,saved};
}
test('home renders four main destinations with illustrated icons and a clean kitchen',()=>{
  const ui=setup();assert.equal(ui.w.document.querySelectorAll('#navigation button').length,4);assert.equal(ui.w.document.querySelector('[data-konsta="app"]').dataset.uiTheme,'material-green');assert.ok(ui.w.document.querySelector('[data-konsta="tabbar"]'));assert.ok(ui.w.document.querySelector('[data-konsta="segmented"]'));assert.equal(ui.w.document.querySelectorAll('#navigation img').length,4);assert.match(ui.w.document.querySelector('.brand-mark img').src,/navigation\/v1\/128\/logo.png/);assert.match(ui.w.document.body.textContent,/冷藏上层/);assert.match(ui.w.document.body.textContent,/可用 500克/);ui.dom.window.close();
});

test('production native settings hide server configuration and permit explicit offline logout',async()=>{
  const shared=C.seed(),ui=setup(null,null,{user:{id:'offline',nickname:'离线',avatar:''},household:{id:'home',name:'家',invite:'CODE'},members:[],revision:1,snapshot:{state:shared,recipeData:{version:2,recipes:shared.recipes,evidence:{}}}});let disconnected=false;
  await new Promise(resolve=>setImmediate(resolve));
  ui.w.NativeBridge={native:()=>true,root:()=> 'https://old.example'};
  Object.assign(ui.w.AccountClient,{user:{id:'offline',nickname:'离线'},offline:true,disconnectLocal:async()=>{disconnected=true;ui.w.AccountClient.user=null;}});
  ui.click('nav','page','mine');ui.click('settings');
  assert.equal(ui.find('server-settings'),undefined);assert.equal(ui.find('jobs'),undefined);assert.equal(disconnected,false);
  ui.click('account-logout');ui.click('confirm-logout');await new Promise(resolve=>setImmediate(resolve));
  assert.equal(disconnected,true);assert.equal(ui.w.document.querySelector('[name="url"]'),null);ui.dom.window.close();
});

test('meal diary gives a short inventory note rather than listing raw ingredients',()=>{
  const initial=C.seed();initial.records=[{id:'record',at:new Date().toISOString(),dishes:[{name:'番茄炒蛋'}],unrecorded:['猪肉','鸡蛋','葱姜蒜','生抽']}];initial.page='mine';
  const ui=setup(initial),before=JSON.stringify(ui.saved());ui.click('record');const body=ui.w.document.querySelector('#sheet-body').textContent;
  assert.match(body,/番茄炒蛋/);assert.match(body,/这餐有部分用量未记录，相关库存未自动扣减/);
  assert.doesNotMatch(body,/猪肉|葱姜蒜|生抽/);assert.equal(JSON.stringify(ui.saved()),before);ui.dom.window.close();
});

test('authenticated household loads from the API and caches only personal view preferences',async()=>{
  const shared=C.seed();shared.stocks=[];
  const account={user:{id:'verified',nickname:'小禾',avatar:''},household:{id:'home',name:'一起的家',invite:'CODE'},members:[],revision:1,snapshot:{state:shared,recipeData:{version:2,recipes:shared.recipes,evidence:{}}}};
  const ui=setup(null,null,account);await new Promise(resolve=>setImmediate(resolve));
  assert.equal(ui.w.AccountClient.user.id,'verified');ui.click('nav','page','mine');
  assert.match(ui.w.document.querySelector('.profile-card').textContent,/小禾.*一起的家/);
  ui.click('role','role','foodie');
  const cached=JSON.parse(ui.w.localStorage.getItem('together-account-cache-verified'));
  assert.deepEqual(Object.keys(cached.state).sort(),['page','role','spaceIndex']);assert.equal(cached.state.role,'foodie');assert.equal(ui.saved(),null);
  ui.dom.window.close();
});

test('space settings rename, confirm deletion and keep food accessible after deleting the last space',()=>{
  const initial=C.seed(),ui=setup(initial);
  ui.click('layout');assert.equal(ui.w.document.querySelector('#sheet-title').textContent,'空间设置');
  assert.equal(ui.w.document.querySelector('[name="name"]').value,'厨房冰箱');
  ui.submit({name:'小冰箱'});assert.equal(ui.w.document.querySelector('.fridge-top strong').textContent,'小冰箱');
  assert.match(ui.w.document.querySelector('.space-tabs').textContent,/小冰箱/);
  ui.click('layout');ui.click('delete-space');assert.match(ui.w.document.querySelector('#sheet-body').textContent,/本餐预留都会保留/);
  assert.equal(ui.saved().state.spaces.length,2);
  ui.click('layout','id','fridge');assert.equal(ui.w.document.querySelector('[name="name"]').value,'小冰箱');
  ui.click('delete-space');ui.click('confirm-delete-space');
  const saved=ui.saved().state;assert.equal(saved.spaces.length,1);assert.match(ui.w.document.querySelector('#screen').textContent,/还没安顿的食材/);
  assert.equal(saved.stocks.find(stock=>stock.id==='pork').space,null);assert.equal(saved.stocks.find(stock=>stock.id==='pork').quantity,500);
  ui.click('stock','id','pork');assert.match(ui.w.document.querySelector('#sheet-body').textContent,/500克可用/);ui.click('close');
  ui.click('layout');ui.click('delete-space');ui.click('confirm-delete-space');assert.match(ui.w.document.querySelector('#screen').textContent,/还没有储物空间/);
  ui.click('add-stock');assert.equal(ui.w.document.querySelector('[name="location"]').value,'unplaced');ui.submit({name:'新食材',quantity:40});
  assert.equal(ui.saved().state.stocks.find(stock=>stock.name==='新食材').space,null);
  const snapshot=ui.saved(),reloaded=setup({...snapshot.state,recipes:snapshot.recipeData.recipes});assert.match(reloaded.w.document.querySelector('#screen').textContent,/还没有储物空间/);
  reloaded.click('add-space');reloaded.submit({name:'新橱柜',type:'cupboard',layout:'horizontal'});
  assert.equal(reloaded.w.document.querySelector('.fridge-top strong').textContent,'新橱柜');assert.equal(reloaded.w.document.querySelectorAll('.compartment').length,2);
  ui.dom.window.close();reloaded.dom.window.close();
});

test('compartment preview caps at three while its sheet and search keep every stock accessible',()=>{
  const initial=C.seed();initial.stocks.push(...['第三项鸡蛋','隐藏青椒','隐藏土豆'].map((name,i)=>({id:'extra-'+i,name,quantity:100+i,unit:'克',space:'fridge',zone:0,iconId:'egg'})));
  const ui=setup(initial),zone=ui.w.document.querySelector('.compartment');
  assert.equal(zone.querySelectorAll('.food-tile').length,3);assert.match(zone.querySelector('.compartment-more').textContent,/查看全部 · 5项/);
  assert.doesNotMatch(zone.textContent,/隐藏青椒|隐藏土豆/);assert.equal(ui.w.document.querySelectorAll('.compartment-more').length,1);
  ui.click('zone-stocks');assert.equal(ui.w.document.querySelector('#sheet-title').textContent,'冷藏上层');
  const list=ui.w.document.querySelector('.zone-stock-list');assert.equal(list.querySelectorAll('[data-action="stock"]').length,5);assert.ok(!list.querySelector('[data-id="pork"]'));
  ui.click('stock','id','extra-2');assert.equal(ui.w.document.querySelector('#sheet-title').textContent,'隐藏土豆');assert.match(ui.w.document.querySelector('#sheet-body').textContent,/102克可用/);
  ui.click('zone-stocks');assert.equal(ui.w.document.querySelector('.zone-stock-list').querySelectorAll('[data-action="stock"]').length,5);
  const add=ui.w.document.querySelector('.zone-stock-heading [data-action="add-stock"]');add.click();
  assert.equal(ui.w.document.querySelector('[name="location"]').value,'fridge:0');
  ui.submit({name:'新加食材',quantity:20,unit:'克',location:'fridge:0'});
  assert.equal(ui.w.document.querySelector('.compartment').querySelectorAll('.food-tile').length,3);assert.match(ui.w.document.querySelector('.compartment-more').textContent,/查看全部 · 6项/);
  const search=ui.w.document.querySelector('#stock-search');search.value='隐藏青椒';search.dispatchEvent(new ui.w.Event('input',{bubbles:true}));
  assert.match(ui.w.document.querySelector('#stock-results').textContent,/隐藏青椒/);assert.equal(ui.saved().state.stocks.find(stock=>stock.id==='extra-1').quantity,101);
  ui.dom.window.close();
});

test('inline calendar filters local dates, browses months and keeps settings separate',()=>{
  const initial=C.seed(),now=new Date(),at=day=>new Date(now.getFullYear(),now.getMonth(),day,12).toISOString();
  initial.page='mine';initial.records=[{id:'five',at:at(5),dishes:[{name:'五号的菜'}],unrecorded:[]},{id:'six',at:at(6),dishes:[{name:'六号的菜'}],unrecorded:[]},{id:'old',at:new Date(now.getFullYear(),now.getMonth()-1,5,12).toISOString(),dishes:[{name:'上月的菜'}],unrecorded:[]}];
  const ui=setup(initial),body=()=>ui.w.document.querySelector('#screen').textContent;
  assert.match(body(),/做饭日历/);assert.match(body(),/尚未登录/);assert.equal(ui.w.document.querySelectorAll('.record-card').length,2);
  assert.doesNotMatch(body(),/最近的烟火|原菜谱整理页面|这版可以体验什么|生成我们的菜单卡/);
  const key=[...ui.w.document.querySelectorAll('[data-action="calendar-day"]')].find(button=>button.textContent.trim()==='5').dataset.date;
  ui.click('calendar-day','date',key);assert.equal(ui.w.document.querySelectorAll('.record-card').length,1);assert.match(body(),/五号的菜/);assert.doesNotMatch(body(),/六号的菜/);
  ui.click('calendar-clear');assert.equal(ui.w.document.querySelectorAll('.record-card').length,2);
  ui.click('calendar-month','delta','-1');assert.match(body(),/上月的菜/);assert.doesNotMatch(body(),/五号的菜/);
  ui.click('settings');assert.match(ui.w.document.querySelector('#sheet-body').textContent,/家庭成员与邀请.*导出菜谱备份/);ui.click('family');assert.match(ui.w.document.querySelector('#sheet-title').textContent,/账号服务尚未连接/);ui.dom.window.close();
});

test('current menu sharing includes only selected dishes for both roles',async()=>{
  const initial=C.seed();initial.role='foodie';initial.page='meal';initial.meal.selections=[{recipeId:'demo-pepper',servings:1}];
  const ui=setup(initial),texts=[];
  ui.w.HTMLCanvasElement.prototype.getContext=()=>({fillRect(){},strokeRect(){},beginPath(){},moveTo(){},lineTo(){},stroke(){},fillText(text){texts.push(text);}});
  ui.w.HTMLCanvasElement.prototype.toDataURL=()=> 'data:image/png;base64,test';
  assert.match(ui.w.document.querySelector('#navigation [data-page="recipes"] img').src,/order.png/);
  ui.click('share-menu');await new Promise(resolve=>setImmediate(resolve));
  assert.ok(texts.includes('青椒炒肉'));assert.ok(!texts.includes('番茄炒蛋'));assert.match(ui.w.document.querySelector('#sheet-title').textContent,/分享本餐菜单/);ui.dom.window.close();
});

test('prominent cancel action still requires confirmation and releases reserved stock',()=>{
  const ui=setup();ui.click('nav','page','recipes');ui.click('pick','id','demo-pepper');ui.click('nav','page','meal');ui.click('lock');
  const need=JSON.stringify(['猪肉','克']);ui.click('prepare','id',need);ui.submit({quantity:300});
  assert.ok(ui.find('cancel-meal').classList.contains('cancel-meal-button'));
  ui.click('cancel-meal');assert.equal(ui.saved().state.meal.status,'locked');ui.click('confirm-cancel');
  const saved=ui.saved().state,stock=saved.stocks.find(stock=>stock.id==='pork');
  assert.equal(saved.meal.status,'cancelled');assert.equal(stock.quantity,500);assert.equal(C.available(saved,stock),500);ui.dom.window.close();
});
test('full menu lock, 500g right record and cooking completion preserve 700g',()=>{
  const ui=setup();ui.click('nav','page','recipes');ui.click('pick','id','demo-pepper');ui.click('nav','page','meal');ui.click('lock');
  ui.click('role','role','foodie');ui.click('nav','page','recipes');assert.equal(ui.find('pick','id','demo-pepper').getAttribute('aria-disabled'),'true');assert.match(ui.w.document.body.textContent,/本餐菜单已固定/);
  ui.click('role','role','chef');ui.click('nav','page','meal');const need=JSON.stringify(['猪肉','克']);ui.click('prepare','id',need); // first matching button is left
  ui.click('close');const right=[...ui.w.document.querySelectorAll('[data-action="prepare"]')].find(element=>element.dataset.id===need&&element.dataset.type==='right');right.click();ui.submit({quantity:500,unit:'克'});
  assert.equal(ui.saved().state.stocks.find(row=>row.id==='pork').quantity,1000);assert.match(ui.w.document.body.textContent,/已经备好了/);
  ui.click('begin');ui.click('finish');assert.equal(ui.saved().state.stocks.find(row=>row.id==='pork').quantity,700);assert.equal(ui.saved().state.records.length,1);
  const restored=setup({...ui.saved().state,recipes:ui.saved().recipeData.recipes});assert.match(restored.w.document.body.textContent,/又一起好好吃了一餐/);assert.equal(restored.saved().state.records.length,1);restored.dom.window.close();ui.dom.window.close();
});

test('locked menu explains blocked picks for both roles without changing the meal',()=>{
  const ui=setup();ui.click('nav','page','recipes');ui.click('pick','id','demo-pepper');ui.click('nav','page','meal');ui.click('lock');
  let timeout;ui.w.setTimeout=(callback,duration)=>{timeout={callback,duration};return 1;};
  const mealBefore=JSON.stringify(ui.saved().state.meal),stocksBefore=JSON.stringify(ui.saved().state.stocks);
  for(const role of ['chef','foodie']) {
    ui.click('role','role',role);ui.click('nav','page','recipes');
    for(const id of ['demo-pepper','demo-tomato']) {
      const pick=ui.find('pick','id',id);assert.equal(pick.disabled,false);assert.equal(pick.getAttribute('aria-disabled'),'true');
      ui.click('pick','id',id);assert.equal(ui.w.document.getElementById('toast').hidden,false);assert.equal(ui.w.document.getElementById('toast').textContent,'本餐菜单已固定，暂无法点菜');
      assert.equal(timeout.duration,2400);timeout.callback();assert.equal(ui.w.document.getElementById('toast').hidden,true);
    }
    ui.click('random');assert.equal(ui.w.document.getElementById('sheet').open,false);assert.equal(ui.w.document.getElementById('toast').textContent,'本餐菜单已固定，暂无法点菜');
    assert.equal(JSON.stringify(ui.saved().state.meal),mealBefore);assert.equal(JSON.stringify(ui.saved().state.stocks),stocksBefore);
  }
  ui.dom.window.close();
});
test('right can be repeated on previously unrecorded food: 200g then 100g',()=>{
  const initial=C.seed();initial.stocks=initial.stocks.filter(row=>row.id!=='pork');const ui=setup(initial);
  ui.click('nav','page','recipes');ui.click('pick','id','demo-pepper');ui.click('nav','page','meal');ui.click('lock');const id=JSON.stringify(['猪肉','克']);
  const right=()=>[...ui.w.document.querySelectorAll('[data-action="prepare"]')].find(element=>element.dataset.id===id&&element.dataset.type==='right').click();
  right();ui.submit({quantity:200,unit:'克'});assert.match(ui.w.document.body.textContent,/这餐已备 200克/);assert.match(ui.w.document.body.textContent,/100克/);
  right();ui.submit({quantity:100,unit:'克'});assert.equal(ui.saved().state.operations.length,2);assert.equal(ui.w.document.querySelectorAll('[data-swipe]').length,2);ui.dom.window.close();
});
test('actual pointer handlers open right for right swipe and left for left swipe',()=>{
  const ui=setup();ui.click('nav','page','recipes');ui.click('pick','id','demo-pepper');ui.click('nav','page','meal');ui.click('lock');
  const row=[...ui.w.document.querySelectorAll('[data-swipe]')].find(element=>element.dataset.need===JSON.stringify(['猪肉','克']));
  function pointer(type,x){const event=new ui.w.Event(type,{bubbles:true});Object.assign(event,{clientX:x,clientY:100,pointerId:1});row.dispatchEvent(event);}
  pointer('pointerdown',100);pointer('pointermove',170);pointer('pointerup',170);assert.match(ui.w.document.querySelector('#sheet-title').textContent,/补录/);
  ui.w.document.getElementById('sheet').close();pointer('pointerdown',170);pointer('pointerup',100);assert.match(ui.w.document.querySelector('#sheet-title').textContent,/家里已经记录/);ui.dom.window.close();
});
test('new storage and manual recipe work without destroying legacy evidence',()=>{
  const old=[{id:'old',name:'旧菜',servings:1,targetServings:3,selected:true,ingredients:[{name:'番茄',quantity:100,unit:'克'}],steps:['炒熟'],evidence:[{kind:'article',text:'番茄100克炒熟'}]}];
  const ui=setup(null,old);ui.click('add-space');ui.submit({name:'阳台冰箱',type:'fridge',layout:'two'});assert.equal(ui.saved().state.spaces.length,3);
  ui.click('nav','page','recipes');ui.click('add-recipe');ui.click('manual');ui.submit({name:'我的鸡蛋',ingredientName:'鸡蛋',ingredientQuantity:2,ingredientUnit:'个',recipeStep:'煎熟'});
  assert.match(ui.w.document.body.textContent,/我的鸡蛋/);const legacy=JSON.parse(ui.w.localStorage.getItem('together-recipes'));assert.equal(legacy.version,2);const oldCard=legacy.recipes.find(row=>row.id==='old');assert.equal(oldCard.selected,true);assert.equal(oldCard.targetServings,3);assert.equal(legacy.evidence[oldCard.evidenceIds[0]].text,'番茄100克炒熟');ui.dom.window.close();
});
test('streamed recipes remain a review until confirmation, including partial results on truncation',async()=>{
  const ui=setup();let controller;
  const stream=new ReadableStream({start(value){controller=value;}});
  ui.w.fetch=async()=>new Response(stream,{headers:{'Content-Type':'application/x-ndjson'}});
  ui.click('nav','page','recipes');ui.click('add-recipe');ui.click('import');ui.submit({share:'https://example.com/public-recipe',article:''});
  const encoder=new TextEncoder();
  assert.equal(ui.w.document.querySelector('#sheet-title').textContent,'正在整理菜谱');
  controller.enqueue(encoder.encode(JSON.stringify({type:'source',evidence:[{id:'ev-test',kind:'article',text:'番茄100克炒熟'}]})+'\n'));
  controller.enqueue(encoder.encode(JSON.stringify({type:'recipes',recipes:[{id:'parsed',name:'解析菜谱',servings:1,ingredients:[{name:'番茄',quantity:100,unit:'克'}],steps:['炒熟'],evidenceIds:['ev-test']}],completedGroups:1,totalGroups:2})+'\n'));
  await new Promise(resolve=>setImmediate(resolve));assert.match(ui.w.document.querySelector('#sheet-body').textContent,/解析菜谱/);assert.ok(!ui.saved().recipeData.recipes.find(row=>row.id==='parsed'));assert.equal(ui.find('job-save'),undefined);
  controller.close();await new Promise(resolve=>setImmediate(resolve));assert.match(ui.w.document.querySelector('.form-error').textContent,/连接中断/);assert.ok(!ui.saved().recipeData.recipes.find(row=>row.id==='parsed'));
  ui.click('job-save');await new Promise(resolve=>setImmediate(resolve));assert.ok(ui.saved().recipeData.recipes.find(row=>row.id==='parsed'));assert.equal(ui.w.document.querySelector('#sheet').open,false);ui.dom.window.close();
});

test('successful visible menu and inventory changes do not open snackbars',()=>{
  const ui=setup();ui.click('nav','page','recipes');ui.click('pick','id','demo-pepper');
  assert.equal(ui.w.document.querySelector('#toast').hidden,true);
  ui.click('nav','page','meal');ui.click('lock');assert.equal(ui.w.document.querySelector('#toast').hidden,true);
  ui.click('nav','page','kitchen');ui.click('add-stock');ui.submit({name:'新的鸡蛋',quantity:2,unit:'个',location:'fridge:0'});
  assert.equal(ui.w.document.querySelector('#toast').hidden,true);ui.dom.window.close();
});

test('non-popover fallback places error feedback inside the active modal',async()=>{
  const ui=setup();ui.click('nav','page','mine');ui.click('settings');ui.click('resume-draft');
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(ui.w.document.querySelector('#toast').parentNode,ui.w.document.querySelector('#sheet'));
  assert.equal(ui.w.document.querySelector('#toast').hidden,false);assert.match(ui.w.document.querySelector('#toast').textContent,/没有未完成/);ui.dom.window.close();
});

test('native API endpoint comes from the bundle and ignores the old editable override',()=>{
  const ui=setup();ui.w.APP_API_URL='https://fixed.example';ui.w.localStorage.setItem('together-server-url','https://old.example');
  ui.w.Capacitor={isNativePlatform:()=>true};ui.w.fetch=async()=>{};
  ui.w.eval(fs.readFileSync(path.join(__dirname,'../web/native-bridge.js'),'utf8'));
  assert.equal(ui.w.NativeBridge.root(),'https://fixed.example');assert.equal(ui.w.NativeBridge.setRoot,undefined);ui.dom.window.close();
});

test('cloud generation polls within the original sheet and saves only after one explicit confirmation',async()=>{
  const shared=C.seed(),ui=setup(null,null,{user:{id:'review-user',nickname:'禾',avatar:''},household:{id:'review-home',name:'家',invite:'CODE'},members:[],revision:1,snapshot:{state:shared,recipeData:{version:2,recipes:shared.recipes,evidence:{}}}});
  await new Promise(resolve=>setImmediate(resolve));
  const card={id:'new-generated',name:'新的菜谱',servings:1,ingredients:[{name:'番茄',quantity:100,unit:'克'}],steps:['炒熟'],evidenceIds:['ev-test']};
  let polled=0,created=0;const commands=[],timers=[];
  ui.w.setTimeout=(callback,duration)=>{timers.push({callback,duration});return timers.length;};ui.w.clearTimeout=()=>{};
  ui.w.JobsClient.create=async(kind,input)=>{created++;assert.equal(kind,'link');return {id:'cloud-job',status:'queued',result:{},events:[]};};
  ui.w.JobsClient.get=async()=>{polled++;return {id:'cloud-job',status:'succeeded',result:{recipes:[card],evidence:[{id:'ev-test',kind:'article',text:'番茄100克炒熟'}]},events:[]};};
  ui.w.AccountClient.command=async(kind,payload)=>{commands.push({kind,payload});};
  ui.click('nav','page','recipes');ui.click('add-recipe');ui.click('import');ui.submit({share:'https://xhslink.cn/o/example',article:''});
  await new Promise(resolve=>setImmediate(resolve));assert.equal(created,1);assert.equal(ui.w.document.querySelector('#sheet-title').textContent,'正在整理菜谱');assert.equal(commands.length,0);
  await timers.find(timer=>timer.duration===1500).callback();
  assert.equal(ui.w.document.querySelector('#sheet-title').textContent,'确认菜谱');assert.match(ui.w.document.querySelector('#sheet-body').textContent,/新的菜谱.*确认收藏/);assert.equal(commands.length,0);
  ui.click('job-save');ui.click('job-save');await new Promise(resolve=>setImmediate(resolve));
  assert.equal(commands.length,1);assert.equal(commands[0].kind,'recipe.upsert');assert.equal(commands[0].payload.recipe.id,'new-generated');assert.equal(ui.w.document.querySelector('#sheet').open,false);assert.ok(polled>=2);ui.dom.window.close();
});

test('closing the create sheet does not let a delayed response replace settings',async()=>{
  const shared=C.seed(),ui=setup(null,null,{user:{id:'delayed-user',nickname:'禾',avatar:''},household:{id:'delayed-home',name:'家',invite:'CODE'},members:[],revision:1,snapshot:{state:shared,recipeData:{version:2,recipes:shared.recipes,evidence:{}}}});
  await new Promise(resolve=>setImmediate(resolve));let release;
  ui.w.JobsClient.create=()=>new Promise(resolve=>{release=resolve;});
  ui.click('nav','page','recipes');ui.click('add-recipe');ui.click('generate-text');ui.submit({prompt:'鸡蛋做一道菜'});ui.click('close');ui.click('nav','page','mine');ui.click('settings');
  release({id:'delayed-job',status:'queued',result:{},events:[]});await new Promise(resolve=>setImmediate(resolve));
  assert.equal(ui.w.document.querySelector('#sheet-title').textContent,'设置');assert.equal(ui.w.document.querySelector('.generation-progress'),null);assert.equal(ui.find('server-settings'),undefined);ui.dom.window.close();
});
test('local storage failure rolls back stock changes and displays an error',()=>{
  const ui=setup();ui.click('add-stock');const before=ui.w.document.body.textContent;
  const original=ui.w.Storage.prototype.setItem;ui.w.Storage.prototype.setItem=function(){throw Error('存储空间已满');};
  ui.submit({name:'测试食材',quantity:100,unit:'克',location:'fridge:0'});assert.match(ui.w.document.querySelector('.form-error').textContent,/已满/);assert.ok(!ui.w.document.querySelector('#screen').textContent.includes('测试食材'));
  ui.w.Storage.prototype.setItem=original;ui.dom.window.close();
});
test('meal share card includes the recorded photo and dish names',async()=>{
  const initial=C.seed();initial.page='mine';initial.records=[{id:'record-photo',at:new Date().toISOString(),dishes:[{name:'青椒炒肉'}],unrecorded:[],photo:'data:image/jpeg;base64,demo'}];
  const ui=setup(initial),draws=[],texts=[];
  const context={fillRect(){},strokeRect(){},beginPath(){},moveTo(){},lineTo(){},stroke(){},fillText(text){texts.push(text);},drawImage(...args){draws.push(args);}};
  ui.w.HTMLCanvasElement.prototype.getContext=()=>context;
  ui.w.HTMLCanvasElement.prototype.toDataURL=()=> 'data:image/png;base64,test';
  ui.w.Image=class {naturalWidth=900;naturalHeight=600;decode(){return Promise.resolve();}};
  ui.click('record','id','record-photo');ui.click('share-record','id','record-photo');await new Promise(resolve=>setImmediate(resolve));
  assert.equal(draws.length,1);assert.ok(texts.includes('青椒炒肉'));assert.match(ui.w.document.querySelector('#sheet-body').textContent,/成品照片/);assert.equal(ui.w.document.querySelector('.share-preview').src,'data:image/png;base64,test');ui.dom.window.close();
});
test('static phone preview explains link parsing availability before submission',()=>{
  const ui=setup();ui.w.STATIC_PREVIEW=true;ui.click('nav','page','recipes');ui.click('add-recipe');ui.click('import');
  assert.match(ui.w.document.querySelector('#sheet-body').textContent,/分享链接识别请在电脑页面使用/);assert.equal(ui.w.document.querySelector('[data-form="parse"]'),null);ui.dom.window.close();
});
test('Konsta search updates remain usable after a page rerender',()=>{
  const ui=setup(),errors=[];ui.w.addEventListener('error',event=>errors.push(event.message));
  ui.click('nav','page','recipes');let input=ui.w.document.querySelector('#recipe-search');input.value='青椒';input.dispatchEvent(new ui.w.Event('input',{bubbles:true}));
  assert.equal(ui.w.document.querySelectorAll('.recipe-card').length,1);assert.ok(ui.w.document.querySelector('.recipe-card[data-konsta="card"]'));
  ui.click('pick','id','demo-pepper');assert.equal(ui.saved().state.meal.selections.length,1);
  ui.click('nav','page','kitchen');input=ui.w.document.querySelector('#stock-search');input.value='猪肉';input.dispatchEvent(new ui.w.Event('input',{bubbles:true}));
  ui.click('space','index','1');assert.match(ui.w.document.querySelector('#stock-results').textContent,/猪肉/);assert.deepEqual(errors,[]);ui.dom.window.close();
});
test('Material brand palette is generated from the selected green seed',()=>{
  const css=fs.readFileSync(path.join(__dirname,'../web/ui/konsta-app.css'),'utf8');
  assert.ok(/--k-color-primary:\s*(?:#4caf50|rgb\(76\s*,?\s*175\s*,?\s*80\))/.test(css),'Green brand seed must reach the built CSS');
  assert.match(css,/--k-color-md-light-primary-container:/);assert.match(css,/--k-color-md-light-secondary-container:/);
});

test('stock picker keeps the selected icon when the name is edited and restored',()=>{
  const ui=setup();ui.click('add-stock');
  const name=ui.w.document.querySelector('[data-ingredient-name]');name.value='鸡蛋';name.dispatchEvent(new ui.w.Event('input',{bubbles:true}));
  assert.equal(ui.w.document.querySelector('[data-ingredient-icon]').value,'category-other');
  ui.click('ingredient-toggle');ui.click('ingredient-select','icon','egg');assert.equal(name.value,'鸡蛋');
  name.value='土鸡蛋';name.dispatchEvent(new ui.w.Event('input',{bubbles:true}));
  assert.equal(ui.w.document.querySelector('[data-ingredient-icon]').value,'egg');
  ui.submit({name:'土鸡蛋',quantity:4,unit:'个',location:'fridge:0'});
  const added=ui.saved().state.stocks.find(row=>row.name==='土鸡蛋');assert.equal(added.iconId,'egg');
  const restored=setup({...ui.saved().state,recipes:ui.saved().recipeData.recipes});
  const tile=[...restored.w.document.querySelectorAll('.food-tile')].find(row=>row.textContent.includes('土鸡蛋'));
  assert.match(tile.querySelector('img').src,/egg.png$/);restored.dom.window.close();ui.dom.window.close();
});

test('layout editor changes its spatial fields and preserves stock when reduced',()=>{
  const ui=setup();assert.equal(ui.w.document.querySelector('.dashboard-summary'),null);assert.equal(ui.w.document.querySelector('#screen .idea-banner'),null);
  assert.ok(ui.w.document.querySelector('.fridge-top [data-action="layout"]'));ui.click('layout');
  const select=ui.w.document.querySelector('[data-layout-select]');assert.equal(ui.w.document.querySelectorAll('.zone-name-cell').length,4);
  select.value='horizontal';select.dispatchEvent(new ui.w.Event('change',{bubbles:true}));
  assert.ok(ui.w.document.querySelector('.zone-name-grid.horizontal'));assert.equal(ui.w.document.querySelectorAll('.zone-name-cell').length,2);
  ui.submit({layout:'horizontal','zone-0':'左边冷藏','zone-1':'右边冷冻'});
  const state=ui.saved().state;assert.deepEqual(state.spaces[0].zones,['左边冷藏','右边冷冻']);assert.equal(state.stocks.find(row=>row.id==='pork').zone,1);assert.equal(state.stocks.find(row=>row.id==='pork').quantity,500);
  assert.ok(ui.w.document.querySelector('.compartments.horizontal'));ui.dom.window.close();
});

test('structured recipe ingredients retain independent icons, unknown amounts and evidence',()=>{
  const ui=setup();ui.click('nav','page','recipes');ui.click('add-recipe');ui.click('manual');
  ui.click('ingredient-toggle');ui.click('ingredient-select','icon','egg');
  const first=ui.w.document.querySelector('.recipe-ingredient-row');first.querySelector('[data-ingredient-name]').value='土鸡蛋';first.querySelector('[name="ingredientQuantity"]').value='3';first.querySelector('[name="ingredientUnit"]').value='个';
  ui.click('ingredient-add');const second=ui.w.document.querySelectorAll('.recipe-ingredient-row')[1];second.querySelector('[data-ingredient-name]').value='海盐';
  ui.submit({name:'我的煎蛋',recipeStep:'煎熟'});
  const card=ui.saved().recipeData.recipes.find(row=>row.name==='我的煎蛋');assert.equal(card.ingredients.length,2);assert.equal(card.ingredients[0].iconId,'egg');assert.equal(card.ingredients[0].name,'土鸡蛋');assert.equal(card.ingredients[1].quantity,null);
  const image=[...ui.w.document.querySelectorAll('.recipe-card')].find(row=>row.textContent.includes('我的煎蛋')).querySelector('img');assert.match(image.src,/default-dish.png$/);
  const restored=setup({...ui.saved().state,recipes:ui.saved().recipeData.recipes});restored.click('recipe','id',card.id);restored.click('edit-recipe','id',card.id);assert.equal(restored.w.document.querySelector('[data-ingredient-icon]').value,'egg');restored.dom.window.close();ui.dom.window.close();
});

test('uploaded recipe cover survives save, editing and backup without removing source evidence',async()=>{
  const old=[{id:'old-cover',name:'旧菜',servings:1,ingredients:[{name:'番茄',quantity:100,unit:'克'}],steps:['炒熟'],evidence:[{kind:'article',text:'番茄100克炒熟'}]}];
  const ui=setup(null,old);ui.click('nav','page','recipes');ui.click('recipe','id','old-cover');ui.click('edit-recipe','id','old-cover');
  ui.w.URL.createObjectURL=()=> 'blob:test';ui.w.URL.revokeObjectURL=()=>{};
  ui.w.Image=class {naturalWidth=800;naturalHeight=600;decode(){return Promise.resolve();}};
  ui.w.HTMLCanvasElement.prototype.getContext=()=>({fillRect(){},drawImage(){}});ui.w.HTMLCanvasElement.prototype.toDataURL=()=> 'data:image/jpeg;base64,dGVzdA==';
  const file=ui.w.document.querySelector('#recipe-cover-file');Object.defineProperty(file,'files',{value:[new ui.w.File(['image'],'cover.png',{type:'image/png'})]});file.dispatchEvent(new ui.w.Event('change',{bubbles:true}));
  await new Promise(resolve=>setImmediate(resolve));assert.equal(ui.w.document.querySelector('.recipe-cover-editor img').src,'data:image/jpeg;base64,dGVzdA==');
  ui.submit({name:'旧菜',recipeStep:'炒熟'});
  const backup=ui.saved().recipeData,card=backup.recipes.find(row=>row.id==='old-cover');assert.equal(card.coverImage,'data:image/jpeg;base64,dGVzdA==');assert.equal(backup.evidence[card.evidenceIds[0]].text,'番茄100克炒熟');assert.equal(JSON.parse(ui.w.localStorage.getItem('together-recipes')).recipes.find(row=>row.id==='old-cover').coverImage,card.coverImage);
  ui.click('recipe','id','old-cover');ui.click('edit-recipe','id','old-cover');assert.equal(ui.w.document.querySelector('.recipe-cover-editor img').src,card.coverImage);ui.dom.window.close();
});

test('Konsta menu selects layout and location; positioned food can move without changing quantity',()=>{
  const ui=setup();ui.click('layout');ui.click('select-toggle');
  assert.ok(ui.w.document.querySelector('[data-konsta="menu-list"]'));assert.equal(ui.w.document.querySelector('[role="combobox"]').getAttribute('aria-expanded'),'true');
  ui.click('select-option','value','horizontal');assert.equal(ui.w.document.querySelector('.select-value').textContent,'左右两侧');assert.equal(ui.w.document.querySelectorAll('.zone-name-cell').length,2);
  ui.w.document.getElementById('sheet').close();ui.click('stock','id','egg');ui.click('move-stock');ui.click('select-toggle');ui.click('select-option','value','cupboard:1');ui.submit({});
  const stock=ui.saved().state.stocks.find(row=>row.id==='egg');assert.equal(stock.space,'cupboard');assert.equal(stock.zone,1);assert.equal(stock.quantity,6);assert.equal(stock.iconId,'egg');
  ui.click('space','index','1');ui.click('stock','id','egg');assert.match(ui.w.document.querySelector('#sheet-body').textContent,/料理橱柜 · 米面粮油/);ui.dom.window.close();
});

test('step rows save in order and unit aliases keep physical amounts and source evidence',()=>{
  const old=[{id:'aliases',name:'旧菜',servings:2,ingredients:[{name:'猪肉',quantity:400,unit:'g',evidence:'原文400g'},{name:'面粉',quantity:1,unit:'kg',evidence:'原文1kg'}],steps:['切肉','翻炒'],evidence:[{kind:'article',text:'原始内容'}]}];
  const ui=setup(null,old);ui.click('nav','page','recipes');ui.click('recipe','id','aliases');
  assert.ok(ui.w.document.querySelector('.detail-title-row [data-action="edit-recipe"]'));assert.ok(!ui.w.document.querySelector('#sheet-body').textContent.includes('原配方'));
  ui.click('edit-recipe','id','aliases');assert.equal(ui.w.document.querySelector('[name="servings"]'),null);
  const unitInputs=ui.w.document.querySelectorAll('[name="ingredientUnit"]');assert.equal(unitInputs[0].value,'克');assert.equal(unitInputs[1].value,'千克');assert.ok(![...unitInputs[0].options].some(option=>option.value==='g'));
  const before=C.needsFor([{...old[0],targetServings:2}]);ui.click('step-add');ui.w.document.querySelectorAll('[name="recipeStep"]')[2].value='出锅';ui.w.document.querySelectorAll('[data-action="step-remove"]')[1].click();
  assert.equal(ui.w.document.querySelectorAll('.step-number')[1].textContent,'第 2 步');ui.submit({name:'旧菜'});
  const card=ui.saved().recipeData.recipes.find(row=>row.id==='aliases');assert.deepEqual(card.steps,['切肉','出锅']);assert.equal(card.ingredients[0].evidence,'原文400g');assert.equal(card.ingredients[1].quantity,1);assert.equal(card.servings,1);assert.deepEqual(C.needsFor([{...card,targetServings:1}]).map(row=>row.required),before.map(row=>row.required));
  ui.click('add-recipe');ui.click('manual');ui.submit({name:'新菜',ingredientName:'鸡蛋',ingredientQuantity:1,ingredientUnit:'个',recipeStep:'煎熟'});assert.equal(ui.saved().recipeData.recipes.find(row=>row.name==='新菜').servings,1);ui.dom.window.close();
});

test('one complete recipe is one portion; legacy draft quantities and locked meals survive migration',()=>{
  const initial=C.seed();C.toggleDish(initial,'demo-pepper');C.setServings(initial,'demo-pepper',3);
  const oldAmounts=C.needsFor(C.draftDishes(initial)).map(row=>row.required),ui=setup(initial);
  ui.click('nav','page','meal');const migrated=ui.saved(),recipes=migrated.recipeData.recipes,state={...migrated.state,recipes};
  assert.equal(recipes.find(row=>row.id==='demo-pepper').servings,1);assert.equal(state.meal.selections[0].servings,1.5);assert.deepEqual(C.needsFor(C.draftDishes(state)).map(row=>row.required),oldAmounts);
  const restored=setup(state);restored.click('nav','page','meal');assert.equal(restored.saved().state.meal.selections[0].servings,1.5);restored.dom.window.close();ui.dom.window.close();
  C.lock(initial);const frozen=C.clone(initial.meal),locked=setup(initial);locked.click('nav','page','meal');assert.deepEqual(locked.saved().state.meal,frozen);locked.dom.window.close();
});
