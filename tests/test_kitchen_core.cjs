const test=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const C=require('../web/kitchen-core.js');

function meal(quantity=500) {
  const state=C.seed();state.stocks.find(row=>row.id==='pork').quantity=quantity;
  C.toggleDish(state,'demo-pepper');C.lock(state);
  return {state,need:state.meal.needs.find(row=>row.name==='猪肉'),stock:state.stocks.find(row=>row.id==='pork')};
}

test('space settings validate before changing its name, layout or stocks',()=>{
  const state=C.seed(),before=C.clone(state);
  assert.throws(()=>C.updateSpace(state,'fridge',' ','two',['上','下']),/空间名字/);
  assert.throws(()=>C.updateSpace(state,'fridge','新名字','invalid',[]),/布局/);
  assert.deepEqual(state,before);
  C.updateSpace(state,'fridge','  新冰箱  ','two',['上','下']);
  assert.equal(state.spaces[0].name,'新冰箱');assert.equal(state.spaces[0].zones.length,2);
  assert.equal(state.stocks.find(stock=>stock.id==='pork').zone,1);
  state.role='foodie';assert.throws(()=>C.updateSpace(state,'fridge','别名','two',[]),/主厨/);
  assert.throws(()=>C.deleteSpace(state,'fridge'),/主厨/);
});

test('deleting an occupied space preserves stock and meal reservations through completion',()=>{
  const {state,stock,need}=meal();C.prepare(state,need.id,'left',300);
  const stocks=C.clone(state.stocks),operations=C.clone(state.operations);stock.iconId='pork';
  C.deleteSpace(state,'fridge');
  assert.equal(state.spaceIndex,0);assert.equal(state.spaces[0].id,'cupboard');
  assert.deepEqual(state.operations,operations);
  for(const original of stocks){const current=state.stocks.find(row=>row.id===original.id);assert.equal(current.quantity,original.quantity);assert.equal(current.space,original.space==='fridge'?null:original.space);}
  assert.equal(stock.iconId,'pork');assert.equal(C.available(state,stock),200);
  const restored=C.clone(state);C.begin(restored);C.finish(restored);
  assert.equal(restored.stocks.find(row=>row.id==='pork').quantity,200);
});

test('deleting spaces keeps the active surviving space and supports an empty kitchen',()=>{
  const state=C.seed();state.spaceIndex=1;C.deleteSpace(state,'fridge');
  assert.equal(state.spaces[state.spaceIndex].id,'cupboard');
  const before=C.clone(state);assert.throws(()=>C.deleteSpace(state,'missing'),/找不到/);assert.deepEqual(state,before);
  C.deleteSpace(state,'cupboard');assert.equal(state.spaces.length,0);assert.equal(state.spaceIndex,0);assert.ok(state.stocks.every(stock=>stock.space===null));
});
test('left allocates existing stock and completion consumes exactly once',()=>{
  const {state,need,stock}=meal();C.prepare(state,need.id,'left',300);
  assert.equal(stock.quantity,500);assert.equal(C.available(state,stock),200);
  C.begin(state);const record=C.finish(state);assert.equal(stock.quantity,200);
  assert.equal(C.available(state,stock),200);assert.equal(C.finish(state),record);assert.equal(state.records.length,1);
});
test('right records an additional 500g, uses 300g, leaves previous stock plus 200g',()=>{
  const {state,need,stock}=meal();C.prepare(state,need.id,'right',500,'克');
  assert.equal(stock.quantity,1000);assert.equal(C.available(state,stock),700);assert.equal(C.remaining(state,need),0);
  C.begin(state);C.finish(state);assert.equal(stock.quantity,700);
});
test('unrecorded food can be added in multiple right operations: 200g then 100g',()=>{
  const {state,need}=meal(0);C.prepare(state,need.id,'right',200,'克');
  assert.equal(C.remaining(state,need),100);assert.equal(C.ready(state,need),false);
  C.prepare(state,need.id,'right',100,'克');assert.equal(C.remaining(state,need),0);assert.equal(C.ready(state,need),true);
  assert.equal(C.totalAvailable(state,need),0);assert.equal(state.operations.length,2);
});
test('200g at home followed by a 500g purchase leaves 400g available',()=>{
  const {state,need}=meal(0);C.prepare(state,need.id,'right',200,'克');C.prepare(state,need.id,'right',500,'克');
  assert.equal(C.totalAvailable(state,need),400);C.begin(state);C.finish(state);assert.equal(state.stocks.find(row=>row.id==='pork').quantity,400);
});
test('partial left plus right retains a visible gap until fulfilled',()=>{
  const {state,need}=meal(200);C.prepare(state,need.id,'left',200);assert.equal(C.remaining(state,need),100);
  C.prepare(state,need.id,'right',100,'克');assert.equal(C.ready(state,need),true);
});
test('invalid or excessive use never alters stock or creates operations',()=>{
  const {state,need,stock}=meal(200),before=C.clone(state);
  for(const q of [0,-10,NaN,Infinity,250])assert.throws(()=>C.prepare(state,need.id,'left',q));
  assert.deepEqual(state,before);assert.equal(stock.quantity,200);
});
test('locked meal rejects recipe and serving changes from both roles',()=>{
  const {state}=meal();for(const role of ['chef','foodie']){state.role=role;assert.throws(()=>C.toggleDish(state,'demo-tomato'));assert.throws(()=>C.setServings(state,'demo-pepper',4));}
  assert.equal(state.meal.selections.length,1);assert.equal(state.meal.dishes[0].targetServings,2);
});
test('recipe edits after lock cannot change meal snapshot or its quantities',()=>{
  const {state,need}=meal();state.recipes[0].ingredients[0].quantity=999;state.recipes[0].name='已修改';
  assert.equal(need.required,300);assert.equal(state.meal.dishes[0].name,'青椒炒肉');
});
test('cancel releases allocations while retaining genuinely recorded food',()=>{
  const {state,need,stock}=meal();C.prepare(state,need.id,'right',500,'克');assert.equal(C.available(state,stock),700);
  C.cancel(state);assert.equal(stock.quantity,1000);assert.equal(C.available(state,stock),1000);
  C.newMeal(state);assert.equal(state.meal.status,'draft');assert.equal(stock.quantity,1000);
});
test('undo of right restores both recorded stock and prepared amount',()=>{
  const {state,need,stock}=meal();const op=C.prepare(state,need.id,'right',500,'克');C.undo(state,op.id);
  assert.equal(stock.quantity,500);assert.equal(C.remaining(state,need),300);assert.throws(()=>C.undo(state,op.id));
});
test('undo cannot remove food reserved by a later operation',()=>{
  const {state,need}=meal(0);const op=C.prepare(state,need.id,'right',500,'克');
  state.meal.needs.push({id:'extra',name:'猪肉',unit:'克',required:200,unknown:0,recipes:['另一道菜']});
  C.prepare(state,'extra','left',200);assert.throws(()=>C.undo(state,op.id),/后续操作/);
});
test('cooking can start with unfinished needs; missing items are not invented',()=>{
  const {state,stock}=meal();C.begin(state);const record=C.finish(state);
  assert.equal(stock.quantity,500);assert.ok(record.unrecorded.includes('猪肉'));
});
test('unknown quantities can be marked ready without deducting estimated grams',()=>{
  const state=C.seed();C.toggleDish(state,'demo-tomato');C.lock(state);const salt=state.meal.needs.find(row=>row.name==='盐');
  const before=C.clone(state.stocks);C.declare(state,salt.id);assert.equal(C.ready(state,salt),true);assert.deepEqual(state.stocks,before);
});
test('right on an unknown need records stock without guessing consumption',()=>{
  const state=C.seed();C.toggleDish(state,'demo-tomato');C.lock(state);const salt=state.meal.needs.find(row=>row.name==='盐');
  C.prepare(state,salt.id,'right',100,'克');assert.equal(state.stocks.find(row=>row.name==='盐').quantity,100);
  C.declare(state,salt.id);C.begin(state);C.finish(state);assert.equal(state.stocks.find(row=>row.name==='盐').quantity,100);
});
test('manual reduction cannot consume food already reserved for this meal',()=>{
  const {state,need,stock}=meal();C.prepare(state,need.id,'left',300);assert.throws(()=>C.reduceStock(state,stock.id,250));
  C.reduceStock(state,stock.id,100);assert.equal(C.available(state,stock),100);C.begin(state);C.finish(state);assert.equal(stock.quantity,100);
});
test('need aggregation normalizes supported aliases and units only',()=>{
  const rows=C.needsFor([{name:'菜',servings:2,targetServings:4,ingredients:[{name:'西红柿',quantity:.1,unit:'kg'},{name:'番茄',quantity:100,unit:'g'},{name:'鸡蛋',quantity:2,unit:'枚'},{name:'盐',quantity:null,unit:'',pending:true}]}]);
  assert.equal(rows.find(row=>row.name==='番茄').required,400);assert.equal(rows.find(row=>row.name==='鸡蛋').unit,'个');assert.equal(rows.find(row=>row.name==='盐').required,null);
});
test('random choices are unique, retain locked choices, and handle insufficient recipes',()=>{
  const rows=C.seed().recipes;const result=C.sample(rows,2,['demo-tomato'],()=>.3);assert.equal(result.length,2);assert.equal(result[0].id,'demo-tomato');assert.equal(new Set(result.map(row=>row.id)).size,2);
  assert.equal(C.sample(rows,6).length,3);assert.throws(()=>C.sample(rows,1,['demo-tomato','demo-pepper']));
});
test('state survives serialization during preparation and can complete after reload',()=>{
  const {state,need}=meal();C.prepare(state,need.id,'left',300);const restored=C.clone(state);C.begin(restored);C.finish(restored);
  assert.equal(restored.stocks.find(row=>row.id==='pork').quantity,200);assert.equal(state.stocks.find(row=>row.id==='pork').quantity,500);
});
test('phone HTTP UUID fallback works without crypto.randomUUID',()=>{
  const sandbox={crypto:{getRandomValues:array=>{array.fill(17);return array;}},Uint8Array,module:{exports:{}}};
  vm.runInNewContext(fs.readFileSync(require.resolve('../web/ids.js'),'utf8'),sandbox);
  assert.match(sandbox.module.exports.uuid(),/^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/);
});

test('moving stock preserves its reservation, identity and eventual consumption',()=>{
  const {state,stock,need}=meal();C.prepare(state,need.id,'left',300);
  const operations=C.clone(state.operations),id=stock.id;stock.iconId='pork';
  C.moveStock(state,id,'cupboard',1);assert.equal(stock.quantity,500);assert.equal(stock.iconId,'pork');assert.equal(C.available(state,stock),200);assert.deepEqual(state.operations,operations);
  assert.throws(()=>C.moveStock(state,id,'cupboard',9),/有效/);assert.equal(stock.zone,1);
  C.moveStock(state,id,null);assert.equal(stock.space,null);assert.equal(stock.zone,0);
  C.begin(state);C.finish(state);assert.equal(stock.quantity,200);assert.equal(stock.id,id);
  state.role='foodie';assert.throws(()=>C.moveStock(state,id,'fridge',0),/主厨/);
});
