/* Local prototype state. Household authentication/sync will replace this adapter. */
(() => {
  const clone = value => JSON.parse(JSON.stringify(value));
  const uid = typeof module!=='undefined' ? require('./ids.js').uuid : RecipeIds.uuid;
  const positive = value => {
    const number = Number(value);
    if (!Number.isFinite(number) || number <= 0) throw Error('请输入大于 0 的数量');
    return number;
  };
  const tidy = number => Math.round(number * 10000) / 10000;
  const foodName = name => ({西红柿:'番茄',马铃薯:'土豆'})[name.trim()] || name.trim();
  function amount(quantity, unit) {
    const units = {g:['克',1],kg:['克',1000],千克:['克',1000],ml:['毫升',1],升:['毫升',1000],颗:['个',1],枚:['个',1]};
    const [canonical, factor] = units[unit] || [unit,1];
    return {quantity:tidy(quantity * factor),unit:canonical};
  }
  const demoRecipes = () => [
    {id:'demo-pepper',name:'青椒炒肉',servings:2,targetServings:2,tag:'下饭担当',minutes:15,tone:'orange',emoji:'🫑',ingredients:[{name:'猪肉',quantity:300,unit:'克'},{name:'青椒',quantity:150,unit:'克'},{name:'生抽',quantity:1,unit:'勺'}],steps:['猪肉切薄片，青椒切块。','热锅下猪肉，炒至变色后加入青椒。','加生抽翻炒均匀，青椒断生即可出锅。'],evidenceIds:[]},
    {id:'demo-tomato',name:'番茄炒蛋',servings:2,targetServings:2,tag:'家常小幸福',minutes:10,tone:'red',emoji:'🍅',ingredients:[{name:'番茄',quantity:300,unit:'克'},{name:'鸡蛋',quantity:3,unit:'个'},{name:'盐',quantity:null,unit:'',pending:true}],steps:['番茄切块，鸡蛋打散。','先将鸡蛋炒至凝固，盛出。','番茄炒出汁，倒回鸡蛋，加盐炒匀。'],evidenceIds:[]},
    {id:'demo-broccoli',name:'蒜蓉西兰花',servings:2,targetServings:2,tag:'添一抹绿',minutes:12,tone:'green',emoji:'🥦',ingredients:[{name:'西兰花',quantity:300,unit:'克'},{name:'蒜',quantity:10,unit:'克'},{name:'盐',quantity:null,unit:'',pending:true}],steps:['西兰花切小朵，蒜切末。','西兰花焯水后沥干。','炒香蒜末，加入西兰花和盐，翻炒均匀。'],evidenceIds:[]}
  ];
  function seed() {
    return {version:1,role:'chef',page:'kitchen',spaceIndex:0,
      spaces:[{id:'fridge',name:'厨房冰箱',type:'fridge',layout:'four',zones:['冷藏上层','冷藏下层','冷冻左格','冷冻右格']},{id:'cupboard',name:'料理橱柜',type:'cupboard',layout:'two',zones:['常用调味','米面粮油']}],
      stocks:[{id:'pork',name:'猪肉',quantity:500,unit:'克',space:'fridge',zone:2},{id:'tomato',name:'番茄',quantity:200,unit:'克',space:'fridge',zone:0},{id:'egg',name:'鸡蛋',quantity:6,unit:'个',space:'fridge',zone:1},{id:'broccoli',name:'西兰花',quantity:200,unit:'克',space:'fridge',zone:0},{id:'garlic',name:'蒜',quantity:20,unit:'克',space:'cupboard',zone:0},{id:'rice',name:'大米',quantity:800,unit:'克',space:'cupboard',zone:1}],
      recipes:demoRecipes(),meal:{id:uid(),status:'draft',selections:[],dishes:[],needs:[]},operations:[],records:[]};
  }
  function reserved(state, stockId, exceptId) {
    return tidy(state.operations.filter(op => op.status==='active' && op.id!==exceptId).reduce((sum,op) => sum + op.allocations.filter(row => row.stockId===stockId).reduce((s,row) => s+row.quantity,0),0));
  }
  function available(state, stock) {return tidy(Math.max(0,stock.quantity-reserved(state,stock.id)));}
  function allocations(state, needId) {
    return tidy(state.operations.filter(op => op.mealId===state.meal.id && op.needId===needId && op.status==='active').reduce((sum,op) => sum + op.allocations.reduce((s,row) => s+row.quantity,0),0));
  }
  function remaining(state, need) {return need.required===null ? null : tidy(Math.max(0,need.required-allocations(state,need.id)));}
  function ready(state, need) {return Boolean(need.declared || remaining(state,need)===0 && !need.unknown);}
  function matching(state, need) {return state.stocks.filter(stock => foodName(stock.name)===need.name && stock.unit===need.unit);}
  function totalAvailable(state, need) {return tidy(matching(state,need).reduce((sum,stock) => sum+available(state,stock),0));}
  function requireDraft(state) {if(state.meal.status!=='draft') throw Error('这餐菜单已固定，点菜暂时收工啦');}
  function requireChef(state) {if(state.role!=='chef') throw Error('请切换到主厨来操作');}
  function requirePreparing(state) {
    requireChef(state);
    if(state.meal.status!=='locked') throw Error('先确定菜单，再准备食材');
  }
  function toggleDish(state, id) {
    requireDraft(state);
    const index=state.meal.selections.findIndex(row => row.recipeId===id);
    if(index>=0) state.meal.selections.splice(index,1);
    else {const recipe=state.recipes.find(row => row.id===id);if(!recipe) throw Error('找不到这道菜');state.meal.selections.push({recipeId:id,servings:recipe.servings});}
  }
  function setServings(state,id,value) {
    requireDraft(state);
    const row=state.meal.selections.find(row => row.recipeId===id);
    if(!row) throw Error('先选这道菜');
    row.servings=positive(value);
  }
  function needsFor(dishes) {
    const rows=new Map();
    for(const dish of dishes) for(const ingredient of dish.ingredients) {
      const name=foodName(ingredient.name);
      const known=Number.isFinite(ingredient.quantity) && ingredient.quantity>=0 && ingredient.unit && !ingredient.pending;
      const normalized=amount(known ? ingredient.quantity*dish.targetServings/dish.servings : 0,ingredient.unit || '');
      const key=JSON.stringify([name,normalized.unit]);
      if(!rows.has(key)) rows.set(key,{id:key,name,...(ingredient.iconId?{iconId:ingredient.iconId}:{}),unit:normalized.unit,required:null,unknown:0,recipes:[],declared:false});
      const row=rows.get(key);
      if(known) row.required=tidy((row.required || 0)+normalized.quantity);else row.unknown++;
      if(!row.recipes.includes(dish.name)) row.recipes.push(dish.name);
    }
    return [...rows.values()];
  }
  function draftDishes(state) {
    return state.meal.selections.map(selection => {
      const recipe=state.recipes.find(row => row.id===selection.recipeId);
      if(!recipe) throw Error('已选菜谱不存在');
      return {...clone(recipe),targetServings:selection.servings};
    });
  }
  function lock(state) {
    requireChef(state);requireDraft(state);
    if(!state.meal.selections.length) throw Error('先选一道想吃的菜');
    state.meal.dishes=draftDishes(state);state.meal.needs=needsFor(state.meal.dishes);state.meal.status='locked';
  }
  function findNeed(state,id) {const need=state.meal.needs.find(row => row.id===id);if(!need) throw Error('找不到这项食材');return need;}
  function prepare(state,id,type,value,unit) {
    requirePreparing(state);
    const need=findNeed(state,id);
    if(ready(state,need)) throw Error('这项已经准备好了');
    if(!['left','right'].includes(type)) throw Error('准备方式无效');
    const q=positive(value);
    if(type==='left' && need.required===null) throw Error('用量未写明，可以先标记已备好，不自动扣库存');
    const normalized=amount(q,type==='right' ? unit || need.unit || '克' : need.unit);
    if(need.required!==null && normalized.unit!==need.unit) throw Error('请使用与需求相同的单位');
    const outstanding=remaining(state,need);
    if(type==='left' && normalized.quantity>outstanding+0.00001) throw Error('使用量不能超过本餐还差的数量');
    if(type==='left' && normalized.quantity>totalAvailable(state,need)+0.00001) throw Error('家里已记录的可用量不够，可以右滑补录');
    const op={id:uid(),mealId:state.meal.id,needId:id,type,quantity:normalized.quantity,status:'active',allocations:[],stockId:null};
    if(type==='left') {
      let rest=normalized.quantity;
      for(const stock of matching(state,need)) {const take=Math.min(rest,available(state,stock));if(take>0) op.allocations.push({stockId:stock.id,quantity:take});rest=tidy(rest-take);if(!rest) break;}
    } else {
      let stock=state.stocks.find(row => foodName(row.name)===need.name && row.unit===normalized.unit);
      if(!stock) {stock={id:uid(),name:need.name,...(need.iconId?{iconId:need.iconId}:{}),quantity:0,unit:normalized.unit,space:null,zone:0};state.stocks.push(stock);}
      stock.quantity=tidy(stock.quantity+normalized.quantity);op.stockId=stock.id;
      const take=outstanding===null ? 0 : Math.min(normalized.quantity,outstanding);
      if(take>0) op.allocations.push({stockId:stock.id,quantity:take});
    }
    state.operations.push(op);return op;
  }
  function declare(state,id) {requirePreparing(state);const need=findNeed(state,id);if(!need.unknown) throw Error('请按明确数量准备这项食材');need.declared=true;}
  function undo(state,id) {
    requirePreparing(state);
    const op=state.operations.find(row => row.id===id && row.status==='active' && row.mealId===state.meal.id);
    if(!op) throw Error('这次操作已经处理过了');
    if(op.type==='right') {
      const stock=state.stocks.find(row => row.id===op.stockId);
      if(stock.quantity-op.quantity+0.00001<reserved(state,stock.id,op.id)) throw Error('这份食材已经被后续操作使用，暂时不能撤销');
      stock.quantity=tidy(stock.quantity-op.quantity);
    }
    op.status='undone';
  }
  function begin(state) {requireChef(state);if(state.meal.status!=='locked') throw Error('先确定菜单');state.meal.status='cooking';}
  function finish(state) {
    requireChef(state);
    if(state.meal.status==='done') return state.records.find(row => row.mealId===state.meal.id);
    if(state.meal.status!=='cooking') throw Error('先开始烹饪');
    const active=state.operations.filter(op => op.mealId===state.meal.id && op.status==='active');
    const used=new Map();
    for(const op of active) for(const row of op.allocations) used.set(row.stockId,tidy((used.get(row.stockId)||0)+row.quantity));
    for(const [id,q] of used) {const stock=state.stocks.find(row => row.id===id);if(!stock || stock.quantity+0.00001<q) throw Error('库存记录发生变化，请先核对');}
    for(const [id,q] of used) {const stock=state.stocks.find(row => row.id===id);stock.quantity=tidy(stock.quantity-q);}
    const missing=state.meal.needs.filter(need => !ready(state,need)).map(need => need.name);
    active.forEach(op => {op.status='consumed';});state.meal.status='done';
    const record={id:uid(),mealId:state.meal.id,at:new Date().toISOString(),dishes:clone(state.meal.dishes),unrecorded:missing,photo:null};
    state.records.unshift(record);return record;
  }
  function cancel(state) {
    requireChef(state);
    if(!['draft','locked','cooking'].includes(state.meal.status)) throw Error('这餐已经结束');
    state.operations.filter(op => op.mealId===state.meal.id && op.status==='active').forEach(op => {op.status='released';});state.meal.status='cancelled';
  }
  function newMeal(state) {requireChef(state);if(!['done','cancelled'].includes(state.meal.status)) throw Error('先完成或取消当前这餐');state.meal={id:uid(),status:'draft',selections:[],dishes:[],needs:[]};}
  function addStock(state,input) {
    requireChef(state);
    const name=String(input.name || '').trim();if(!name) throw Error('填一下食材名字');
    const normalized=amount(positive(input.quantity),input.unit || '克');
    let stock=state.stocks.find(row => row.name===name && row.unit===normalized.unit && row.space===input.space && row.zone===input.zone);
    if(stock) {stock.quantity=tidy(stock.quantity+normalized.quantity);if(input.iconId)stock.iconId=input.iconId;}
    else {stock={id:uid(),name,...(input.iconId?{iconId:input.iconId}:{}),...normalized,space:input.space || null,zone:input.zone || 0};state.stocks.push(stock);}
    return stock;
  }
  function layoutZones(layout) {
    const rows={four:['左上','右上','左下','右下'],two:['上层','下层'],horizontal:['左侧','右侧']};
    if(!rows[layout])throw Error('请选择有效的布局');
    return [...rows[layout]];
  }
  function moveStock(state,id,spaceId,zone=0) {
    requireChef(state);const stock=state.stocks.find(row=>row.id===id);if(!stock)throw Error('找不到这份食材');
    const space=state.spaces.find(row=>row.id===spaceId);
    if(spaceId!==null && (!space || !Number.isInteger(zone) || zone<0 || zone>=space.zones.length))throw Error('请选择有效的储物位置');
    stock.space=spaceId;stock.zone=spaceId===null?0:zone;
    return stock;
  }
  function setLayout(state,id,layout,names) {
    requireChef(state);const space=state.spaces.find(row=>row.id===id);if(!space)throw Error('找不到这个储物空间');
    const defaults=layoutZones(layout);
    space.layout=layout;space.zones=defaults.map((name,i)=>String(names[i] || name).trim() || name);
    for(const stock of state.stocks)if(stock.space===space.id)stock.zone=Math.min(stock.zone,space.zones.length-1);
  }
  function updateSpace(state,id,name,layout,names) {
    requireChef(state);
    const title=String(name || '').trim();
    if(!title || title.length>30)throw Error('请填写30字以内的空间名字');
    setLayout(state,id,layout,names);
    state.spaces.find(row=>row.id===id).name=title;
  }
  function deleteSpace(state,id) {
    requireChef(state);
    const index=state.spaces.findIndex(row=>row.id===id);
    if(index<0)throw Error('找不到这个储物空间');
    const selected=state.spaces[state.spaceIndex]?.id;
    for(const stock of state.stocks)if(stock.space===id){stock.space=null;stock.zone=0;}
    state.spaces.splice(index,1);
    const remainingIndex=state.spaces.findIndex(row=>row.id===selected);
    state.spaceIndex=remainingIndex>=0?remainingIndex:Math.max(0,Math.min(index,state.spaces.length-1));
  }
  function reduceStock(state,id,value) {
    requireChef(state);const stock=state.stocks.find(row => row.id===id);if(!stock) throw Error('找不到这份食材');
    const q=positive(value);if(q>available(state,stock)+0.00001) throw Error('不能减少超过可用量的食材，本餐已留出的部分要从准备记录撤销');stock.quantity=tidy(stock.quantity-q);
  }
  function sample(recipes,count,lockedIds=[],random=Math.random) {
    const target=Math.min(Math.max(1,Math.floor(positive(count))),recipes.length);
    const locked=recipes.filter(recipe => lockedIds.includes(recipe.id));
    if(locked.length>target) throw Error('锁住的菜比要选的道数多，先解锁一道');
    const pool=recipes.filter(recipe => !lockedIds.includes(recipe.id));
    for(let i=pool.length-1;i>0;i--) {const j=Math.floor(random()*(i+1));[pool[i],pool[j]]=[pool[j],pool[i]];}
    return [...locked,...pool.slice(0,target-locked.length)];
  }
  const api={uid,seed,clone,foodName,amount,available,reserved,remaining,allocations,ready,matching,totalAvailable,toggleDish,setServings,needsFor,draftDishes,lock,prepare,declare,undo,begin,finish,cancel,newMeal,addStock,reduceStock,sample,layoutZones,setLayout,moveStock,updateSpace,deleteSpace};
  if(typeof module!=='undefined') module.exports=api;else globalThis.KitchenCore=api;
})();
