const test = require('node:test');
const assert = require('node:assert/strict');
const {createStore} = require('../web/recipe-data.js');
const {readEvents} = require('../web/parse-stream.js');
const row = {kind:'image_ocr',text:'番茄300克',locator:'第1张图'};
const card = (id, extra = {}) => ({id,name:'番茄菜',servings:2,targetServings:4,selected:true,
  ingredients:[{name:'番茄',quantity:300,unit:'克'}],steps:['炒熟'],...extra});

test('legacy cards and evidence migrate losslessly and deduplicate in storage', () => {
  const old = [card('a',{evidence:[row]}),card('b',{evidence:[row]})];
  const store = createStore(old);
  assert.equal(Object.keys(store.evidence).length,1);
  assert.equal(store.recipes[0].selected,true);
  assert.equal(store.recipes[0].targetServings,4);
  assert.equal(store.recipes[0].evidence,undefined);
  const backup=store.snapshot(store.recipes);
  const restored=createStore(JSON.parse(JSON.stringify(backup)));
  assert.deepEqual(restored.resolve(restored.recipes[0]),store.resolve(store.recipes[0]));
  assert.deepEqual(restored.recipes,store.recipes);
});

test('server IDs can reuse legacy evidence without losing references', () => {
  const store=createStore([card('old',{evidence:[row]})]);
  store.register([{...row,id:'ev-server'}]);
  const incoming=store.normalize(card('new',{evidenceIds:['ev-server']}));
  assert.equal(incoming.evidenceIds[0],store.recipes[0].evidenceIds[0]);
  assert.equal(store.resolve(incoming)[0].text,row.text);
});

test('invalid shared backups fail and deletion removes unreferenced evidence from snapshot', () => {
  assert.throws(()=>createStore({version:2,recipes:[card('a',{evidenceIds:['missing']})],evidence:{}}),/缺少/);
  const store=createStore([card('a',{evidence:[row]})]);
  assert.deepEqual(store.snapshot([]).evidence,{});
  assert.equal(store.resolve(store.recipes[0]).length,1);
});

test('ID conflicts cannot overwrite original evidence', () => {
  const store=createStore();store.register([{...row,id:'ev-a'}]);
  assert.throws(()=>store.register([{...row,id:'ev-a',text:'盐5克'}]),/冲突/);
  assert.equal(store.evidence['ev-a'].text,row.text);
});

test('stream delivers a card before completion and decodes fragmented UTF-8', async () => {
  let continueStream;const gate=new Promise(resolve=>continueStream=resolve);
  const encoder=new TextEncoder();let first=false;
  const body=new ReadableStream({async start(controller){
    const bytes=encoder.encode(JSON.stringify({type:'recipes',recipes:[card('a')]})+'\n');
    for(const byte of bytes)controller.enqueue(Uint8Array.of(byte));
    await gate;
    controller.enqueue(encoder.encode('{"type":"done","recipeCount":1}\n'));controller.close();
  }});
  await readEvents(new Response(body,{headers:{'Content-Type':'application/x-ndjson'}}),event=>{
    if(event.type==='recipes'){first=true;assert.equal(event.recipes[0].name,'番茄菜');continueStream()}
    if(event.type==='done')assert.equal(first,true);
  });
});

test('truncated stream reports failure after delivering the successful card', async () => {
  const events=[];
  await assert.rejects(readEvents(new Response('{"type":"recipes","recipes":[]}\n',
    {headers:{'Content-Type':'application/x-ndjson'}}),event=>events.push(event)),/连接中断/);
  assert.equal(events.length,1);
});

test('JSON clients and old per-card evidence remain compatible', async () => {
  const events=[];
  await readEvents(new Response(JSON.stringify({recipes:[card('a',{evidence:[row]})],evidence:[row]}),
    {headers:{'Content-Type':'application/json'}}),event=>events.push(event));
  assert.deepEqual(events.map(e=>e.type),['source','recipes','done']);
  const store=createStore();store.register(events[0].evidence);
  assert.equal(store.resolve(store.normalize(events[1].recipes[0])).length,1);
});
