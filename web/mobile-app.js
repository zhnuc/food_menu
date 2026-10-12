/* Mobile interaction prototype. Real link parsing reuses RecipeStream/RecipeData. */
(() => {
  const C=KitchenCore, A=AccountClient, $=id=>document.getElementById(id), KEY='together-mobile-prototype-v1';
  const esc=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const icon=name=>`<svg class="icon" aria-hidden="true"><use href="#i-${name}"/></svg>`;
  const fmt=value=>Number(Number(value).toFixed(2)).toLocaleString('zh-CN');
  const displayUnit=value=>({g:'克',kg:'千克',ml:'毫升',颗:'个',枚:'个'})[String(value || '').trim().toLowerCase()] || String(value || '').trim();
  const oneRecipe=card=>({...card,servings:1,...(Number.isFinite(card.targetServings)?{targetServings:card.targetServings/card.servings}:{})});
  const foodImage=(name,iconId)=>`<img class="ingredient-image" src="${IngredientIcons.url(name,'other',iconId)}" width="32" height="32" alt="" decoding="async">`;
  const fixedIcon=row=>IngredientIcons.valid(row?.iconId)?row.iconId:IngredientIcons.id(row?.name);
  const safeCover=value=>typeof value==='string' && (window.PrivateAssets?.valid(value) || value.length<=2000000 && /^data:image\/(jpeg|png|webp);base64,[A-Za-z0-9+/]+=*$/.test(value))?value:'';
  const imageAttrs=url=>window.PrivateAssets?window.PrivateAssets.attributes(url):`src="${esc(url)}"`;
  const coverUrl=card=>safeCover(card.coverImage) || store.resolve(card).map(row=>safeAsset(row.asset)).find(Boolean) || `/assets/dishes/v1/256/${({'demo-pepper':'pepper-pork','demo-tomato':'tomato-egg','demo-broccoli':'garlic-broccoli'})[card.id] || 'default-dish'}.png`;
  const dishImage=card=>`<img class="dish-thumbnail" ${imageAttrs(coverUrl(card))} width="40" height="40" alt="" decoding="async">`;
  const safeAsset=value=>/^\/media\/[a-f0-9]{24}\/(?:frame-\d+\.jpg|image-\d+\.(?:jpg|png|webp))$/.test(value || '') ? value : '';
  const safeLink=value=>/^https?:\/\//i.test(value || '') ? value : '';
  let state,store,viewAccountId=null,bootError='',search='',recipeSearch='',randomRows=[],randomLocked=[],randomCount=2,photoRecord=null,toastTimer,parseBusy=false,parseMessage='',parseResume=null,swipe=null,lastSwipe=0,recipeDraft=null,profileDraft=null,calendarMonth=new Date(new Date().getFullYear(),new Date().getMonth(),1),calendarDay='';
  let sheetVersion=0,reviewTimer=null,activeReview=null,latestJob=null,localJob=null;
  const savingJobs=new Set();
  try {
    const saved=JSON.parse(localStorage.getItem(KEY) || 'null');
    const original=RecipeData.createStore(JSON.parse(localStorage.getItem('together-recipes') || '[]'));
    store=RecipeData.createStore(saved?.recipeData || original.snapshot(original.recipes));
    state=saved?.state?.version===1 ? {...saved.state,recipes:store.recipes} : C.seed();
    for(const card of original.recipes) if(!state.recipes.some(row=>row.id===card.id)) state.recipes.push(store.normalize({...card,evidence:original.resolve(card)}));
    state.stocks=state.stocks.map(stock=>({...stock,iconId:fixedIcon(stock)}));
    state.recipes=state.recipes.map(card=>{
      if(card.servings!==1 && state.meal.status==='draft')for(const selection of state.meal.selections)if(selection.recipeId===card.id)selection.servings/=card.servings;
      return store.normalize(oneRecipe({...card,ingredients:card.ingredients.map(row=>({...row,iconId:fixedIcon(row)}))}));
    });
  } catch(error) {state=C.seed();store=RecipeData.createStore();bootError='本机记录读取失败，本次先显示演示数据。原记录未删除。';}

  function snapshot() {const {recipes,...data}=state;return {state:data,recipeData:store.snapshot(recipes)};}
  function persist() {
    // Family photos and recipes stay in the database, avoiding browser-storage limits.
    const data=A.user?{state:{role:state.role,page:state.page,spaceIndex:state.spaceIndex}}:snapshot();
    localStorage.setItem(A.user?'together-account-cache-'+A.user.id:KEY,JSON.stringify(data));
  }
  function transact(action,shared=true) {
    if(A.user && shared)throw Error('家庭修改需要通过服务器操作接口');
    const before=C.clone(state);
    try {const result=action();persist();render();return result;}
    catch(error) {state=before;throw error;}
  }
  function mutate(kind,payload,local) {
    if(!A.user)return transact(local);
    return A.command(kind,payload,{role:state.role,mealId:state.meal.id});
  }
  function rememberReal(card) {
    if(A.user)return;
    try {
      const original=RecipeData.createStore(JSON.parse(localStorage.getItem('together-recipes') || '[]'));
      const normalized=original.normalize({...card,evidence:store.resolve(card)});
      const index=original.recipes.findIndex(row=>row.id===card.id);
      if(index<0) original.recipes.push(normalized);else original.recipes[index]=normalized;
      localStorage.setItem('together-recipes',JSON.stringify(original.snapshot(original.recipes)));
    } catch(error) {toast('当前页面已保存，旧菜谱备份写入失败，请及时导出备份。');}
  }
  function raiseToast() {
    const target=$('toast');
    if(target.hidePopover && target.matches(':popover-open'))target.hidePopover();
    // A popover outside a modal is still inert, even in the browser top layer.
    const parent=$('sheet').open?$('sheet'):document.body;if(target.parentNode!==parent)parent.append(target);
    if(target.showPopover)target.showPopover();
  }
  function hideToast() {const target=$('toast');if(target.hidePopover && target.matches(':popover-open'))target.hidePopover();target.hidden=true;}
  function toast(message,undoId,duration=3500) {
    clearTimeout(toastTimer);$('toast').hidden=false;
    $('toast').innerHTML=`<span>${esc(message)}</span>${undoId?`<button data-action="undo" data-id="${esc(undoId)}">撤销</button>`:A.pending?'<button data-action="retry-sync">重试同步</button>':''}`;
    raiseToast();toastTimer=setTimeout(hideToast,undoId?9000:duration);
  }
  function region(id,html){if(window.KonstaUI)window.KonstaUI.region(id,html);else $(id).innerHTML=html;}
  function stopReview(){clearTimeout(reviewTimer);reviewTimer=null;activeReview=null;delete $('sheet').dataset.jobId;}
  function sheet(title,body,jobId='') {
    const same=jobId && $('sheet').open && $('sheet').dataset.jobId===jobId,scroll=same?$('sheet').scrollTop:0;
    if(!same){sheetVersion++;stopReview();}
    $('sheet-title').textContent=title;if(window.KonstaUI)window.KonstaUI.sheet(body);else $('sheet-body').innerHTML=body;
    if(jobId)$('sheet').dataset.jobId=jobId;if(!$('sheet').open)$('sheet').showModal();$('sheet').scrollTop=scroll;
    if(!$('toast').hidden)raiseToast();
  }
  function close() {sheetVersion++;stopReview();hideToast();$('sheet').close();}
  $('sheet').addEventListener('close',()=>{sheetVersion++;stopReview();hideToast();document.body.append($('toast'));});
  const button=(label,action,extra='',style='button-primary')=>`<button class="${style}" data-action="${action}" ${extra}>${label}</button>`;
  const heading=(label,english,sub,action='')=>`<div class="page-heading"><div><p class="eyebrow">${english}</p><h1>${label}</h1><p class="subline">${sub}</p></div>${action}</div>`;
  function location(stock) {const space=state.spaces.find(row=>row.id===stock.space);return space ? `${space.name} · ${space.zones[stock.zone] || '未分区'}` : '未分配位置';}
  function quantityLabel(need) {return `${need.required===null?'':fmt(need.required)+esc(need.unit)}${'+'.repeat(Math.min(3,need.unknown))}` || '+';}
  function recipeArt(card) {
    return `<div class="recipe-art ${['red','green','orange'].includes(card.tone)?card.tone:'green'}" aria-hidden="true"><img class="${coverUrl(card).startsWith('/assets/dishes/')?'dish-illustration':''}" loading="lazy" ${imageAttrs(coverUrl(card))} alt=""></div>`;
  }
  function recipeCard(card) {
    const picked=state.meal.selections.some(row=>row.recipeId===card.id),locked=state.meal.status!=='draft';
    return `<article class="recipe-card">${recipeArt(card)}<div class="recipe-info"><span class="tag">${card.id.startsWith('demo-')?esc(card.tag || '演示菜谱'):'我的收藏'}</span><h3>${esc(card.name)}</h3><p>${esc(card.ingredients.slice(0,3).map(row=>row.name).join(' · '))}</p><button class="text-link" data-action="recipe" data-id="${esc(card.id)}">看看做法 ↗</button></div><button class="pick-button ${picked?'picked':''}" data-action="pick" data-id="${esc(card.id)}" aria-label="${picked?'取消选择':'选择'}${esc(card.name)}" aria-pressed="${picked}" aria-disabled="${locked}">${icon(picked?'check':'plus')}</button></article>`;
  }
  function render() {
    if(state.role==='foodie' && state.page==='kitchen') state.page='recipes';
    if(window.KonstaUI)window.KonstaUI.roles(state.role);else document.querySelectorAll('[data-action="role"]').forEach(element=>element.setAttribute('aria-pressed',String(element.dataset.role===state.role)));
    const tabs=[...(state.role==='chef'?[['kitchen','厨房','kitchen']]:[]),['recipes',state.role==='chef'?'菜谱':'点菜',state.role==='chef'?'recipes':'order'],['meal','这一餐','meal'],['mine','我的','mine']];
    const navigation=tabs.map(([page,label,graphic])=>`<button data-action="nav" data-page="${page}" class="${state.page===page?'active':''}" ${state.page===page?'aria-current="page"':''}><img class="navigation-image" src="/assets/navigation/v1/128/${graphic}.png" width="32" height="32" alt=""><span>${label}</span>${page==='meal'&&state.meal.selections.length?`<b class="nav-count">${state.meal.selections.length}</b>`:''}</button>`).join('');
    if(window.KonstaUI)window.KonstaUI.navigation(navigation);else $('navigation').innerHTML=navigation;
    const views={kitchen:kitchenPage,recipes:recipesPage,meal:mealPage,mine:minePage};
    const syncStatus=A.user&&(A.offline||A.syncing||A.pending)?`<p class="hint" role="status">${A.offline?'当前离线 · 正在查看本机留档。 <button class="text-link" data-action="reconnect">重新连接</button>':A.syncing?'正在保存到家庭…':'上次修改尚未确认。 <button class="text-link" data-action="retry-sync">重试同步</button>'}</p>`:'';
    region('screen',`<div class="page-enter">${syncStatus}${(views[state.page] || kitchenPage)()}</div>`);
  }
  function kitchenPage() {
    const index=Math.max(0,Math.min(state.spaceIndex,state.spaces.length-1)),space=state.spaces[index];state.spaceIndex=index;
    const unplaced=state.stocks.filter(row=>!row.space && row.quantity>0);
    return heading('我的厨房','A LITTLE KITCHEN','食材放在哪，打开就知道。',`<button class="circle-button" data-action="add-stock" aria-label="添加食材">${icon('plus')}</button>`)+
      `<label class="search-box">${icon('search')}<input id="stock-search" aria-label="查找食材位置" placeholder="找找食材放在哪里…" value="${esc(search)}"></label><div id="stock-results">${stockResults()}</div>`+
      (space?`<div class="space-tabs">${state.spaces.map((row,i)=>`<button data-action="space" data-index="${i}" class="${i===index?'active':''}">${esc(row.name)}</button>`).join('')}<button class="space-add" data-action="add-space" aria-label="添加储物空间">${icon('plus')}</button></div>`+
      `<section class="fridge ${space.type==='cupboard'?'cupboard':''}" data-space-swipe="true" aria-label="${esc(space.name)}分区"><div class="fridge-top"><strong>${esc(space.name)}</strong><button class="space-edit" data-action="layout" aria-label="设置${esc(space.name)}储物空间">空间设置 ${icon('arrow')}</button></div><div class="compartments ${esc(space.layout)}">${space.zones.map((zone,i)=>compartmentPreview(space,i)).join('')}</div></section><div class="fridge-feet"><i></i><i></i></div>`+
      `<div class="space-caption"><span>左右滑动，看看另一个空间</span><div class="space-dots">${state.spaces.map((row,i)=>`<i class="${i===index?'active':''}"></i>`).join('')}</div></div>`:
      `<div class="empty-state">${icon('fridge')}<h2>还没有储物空间</h2><p>添一个冰箱或橱柜，把食材安顿好。</p>${button('添加储物空间','add-space','','button-secondary')}</div>`)+
      `${unplaced.length?`<div class="section-label"><h2>还没安顿的食材</h2><span>${unplaced.length} 项</span></div><div class="stock-search-list">${unplaced.map(stock=>stockSearchCard(stock)).join('')}</div>`:''}<p class="hint">不必一次盘点整个厨房。准备食材时补录，慢慢就齐了。</p>`;
  }
  function compartmentPreview(space,zone) {
    const stocks=state.stocks.filter(row=>row.space===space.id&&row.zone===zone);
    return `<div class="compartment"><div class="compartment-label"><span>${esc(space.zones[zone])}</span><button data-action="add-stock" data-space="${esc(space.id)}" data-zone="${zone}" aria-label="向${esc(space.zones[zone])}添加食材">${icon('plus')}</button></div>${stocks.slice(0,3).map(stock=>`<button class="food-tile ${C.available(state,stock)===0?'zero':''}" data-action="stock" data-id="${esc(stock.id)}"><span class="food-emoji" aria-hidden="true">${foodImage(stock.name,stock.iconId)}</span><span><strong>${esc(stock.name)}</strong><small>可用 ${fmt(C.available(state,stock))}${esc(stock.unit)}</small></span></button>`).join('') || '<p class="zone-empty">留给下一份新鲜</p>'}${stocks.length>3?`<button class="compartment-more" data-action="zone-stocks" data-space="${esc(space.id)}" data-zone="${zone}" aria-label="查看${esc(space.zones[zone])}全部${stocks.length}项食材">查看全部 · ${stocks.length}项 ${icon('arrow')}</button>`:''}</div>`;
  }
  function openZoneStocks(spaceId,zone) {
    const space=state.spaces.find(row=>row.id===spaceId);
    if(!space || !Number.isInteger(zone) || zone<0 || zone>=space.zones.length)throw Error('找不到这个分区');
    const stocks=state.stocks.filter(row=>row.space===space.id&&row.zone===zone);
    sheet(space.zones[zone],`<div class="zone-stock-heading"><p class="sheet-note">${esc(space.name)} · ${stocks.length}项食材</p><button type="button" class="button-secondary" data-action="add-stock" data-space="${esc(space.id)}" data-zone="${zone}">${icon('plus')}添加食材</button></div><div class="stock-search-list zone-stock-list">${stocks.map(stock=>stockSearchCard(stock,{space:space.id,zone})).join('') || '<p class="hint">这一层还没有食材。</p>'}</div>`);
  }
  function stockSearchCard(stock,origin) {return `<button data-action="stock" data-id="${esc(stock.id)}" ${origin?`data-origin-space="${esc(origin.space)}" data-origin-zone="${origin.zone}"`:''}><span class="food-emoji">${foodImage(stock.name,stock.iconId)}</span><div><strong>${esc(stock.name)} · ${fmt(C.available(state,stock))}${esc(stock.unit)}</strong><small>${esc(location(stock))}</small></div>${icon('arrow')}</button>`;}
  function stockResults() {
    if(!search.trim()) return '';
    const rows=state.stocks.filter(row=>row.name.includes(search.trim()));
    return `<p class="search-results-heading">找到 ${rows.length} 处记录</p><div class="stock-search-list">${rows.map(stockSearchCard).join('') || '<p class="hint">暂时没记录，可以先添加，也可以准备一餐时补录。</p>'}</div>`;
  }
  function recipesPage() {
    const locked=state.meal.status!=='draft';
    return heading(state.role==='chef'?'我们的菜谱':'今天想吃什么？','OUR LITTLE MENU',state.role==='chef'?'把喜欢的味道，留在这一本。':'点几道喜欢的，交给今天的主厨。',`<button class="circle-button" data-action="add-recipe" aria-label="新增菜谱">${icon('plus')}</button>`)+
      `<div class="recipe-tools"><button data-action="random" aria-disabled="${locked}">${icon('dice')}不知道？随机一下</button><span class="count-note">${state.recipes.length} 道收藏</span></div>${A.user?'<button class="generation-history" data-action="jobs">生成记录 '+icon('arrow')+'</button>':''}${latestJob?`<button class="generation-notice" data-action="job-detail" data-id="${esc(latestJob.id)}"><span>${latestJob.status==='succeeded'?'菜谱已生成，确认后收藏':latestJob.status==='failed'?'这次生成需要处理':latestJob.status==='cancelled'?'生成已取消':'菜谱正在生成'}<small>${esc(jobStatus(latestJob.status))}</small></span>${icon('arrow')}</button>`:''}${locked?`<p class="lock-note">${icon('lock')}本餐菜单已固定，可以看做法，暂时不能继续点菜。</p>`:''}`+
      `<label class="search-box">${icon('search')}<input id="recipe-search" aria-label="搜索菜谱" value="${esc(recipeSearch)}" placeholder="搜菜名或食材…"></label>${parseBusy?`<p class="import-status">${esc(parseMessage || '正在整理新菜谱…')}</p>`:''}<div class="recipe-list" id="recipe-results">${recipeResults()}</div>`+
      `<div class="sticky-meal-link"><div><strong>${state.meal.selections.length?`已经选了 ${state.meal.selections.length} 道菜`:'给今天留一点期待'}</strong><small>${state.meal.status==='draft'?'选好后，去安排这一餐。':'本餐菜单与准备进度都在这里。'}</small></div><button data-action="nav" data-page="meal">看看这一餐</button></div>`;
  }
  function recipeResults() {const rows=state.recipes.filter(card=>!recipeSearch || `${card.name} ${card.ingredients.map(row=>row.name).join(' ')}`.includes(recipeSearch));return rows.map(recipeCard).join('') || '<div class="empty-state"><h2>还没找到这道菜</h2><p>试试另一个名字，或者自己记一道。</p></div>';}
  function mealPage() {
    const status=state.meal.status, draft=status==='draft',chef=state.role==='chef';
    const dishes=draft?C.draftDishes(state):state.meal.dishes;
    const labels={draft:'选菜中',locked:'准备中',cooking:'烹饪中',done:'已完成',cancelled:'已取消'};
    let html=heading('今天这一餐','A MEAL TOGETHER','想吃的，慢慢变成桌上的。',`<span class="meal-state">${icon(draft?'meal':'lock')}${labels[status]}</span>`);
    if(!dishes.length && draft) return html+`<div class="empty-state">${icon('meal')}<h2>今晚的菜单，还空着</h2><p>去菜谱点几道喜欢的，再一起准备。</p>${button('去选菜','nav','data-page="recipes"')}</div><button class="idea-banner" data-action="ideas"><span class="idea-mark">${icon('kitchen')}</span><span><strong>先看看家里能做什么</strong><small>用已有食材，找点灵感</small></span>${icon('arrow')}</button>`;
    html+=`<div class="meal-summary">${dishes.map(dish=>`<div class="menu-row"><span class="food-emoji">${dishImage(dish)}</span><div><strong>${esc(dish.name)}</strong><small>${draft?'本餐份数可以调整':fmt(dish.targetServings)+' 份 · 菜单已固定'}</small></div>${draft?`<div class="quantity-stepper"><button data-action="servings" data-id="${esc(dish.id)}" data-delta="-1" aria-label="减少${esc(dish.name)}份数">−</button><span>${fmt(dish.targetServings)}</span><button data-action="servings" data-id="${esc(dish.id)}" data-delta="1" aria-label="增加${esc(dish.name)}份数">＋</button></div><button class="remove" data-action="pick" data-id="${esc(dish.id)}" aria-label="移除${esc(dish.name)}">×</button>`:`<button class="text-link" data-action="meal-recipe" data-id="${esc(dish.id)}">做法</button>`}</div>`).join('')}</div>`;
    html+='<button class="meal-share-link" data-action="share-menu">分享本餐菜单 ↗</button>';
    if(draft) {
      const needs=C.needsFor(dishes);
      html+=`<div class="section-label"><h2>这一餐会用到</h2><span>${needs.length} 项食材</span></div><div class="chips">${needs.map(need=>`<span>${esc(need.name)} ${quantityLabel(need)}</span>`).join('')}</div><p class="hint">确认后菜单固定，美食家不再改菜；食材可以慢慢准备。</p>`;
      return html+ (chef?button(icon('lock')+'就做这些，确定菜单','lock'):`<div class="storage-note">点单已经记下，等主厨确定菜单。</div>`);
    }
    if(status==='locked') {
      const needs=state.meal.needs,done=needs.filter(need=>C.ready(state,need));
      html+=`<div class="section-label"><h2>准备食材</h2><span>已备 ${done.length} / ${needs.length}</span></div><div class="progress-track"><span style="width:${needs.length?done.length/needs.length*100:0}%"></span></div><div class="prepare-guide" aria-label="食材准备方式"><div class="prepare-guide-option"><span class="prepare-guide-arrow" aria-hidden="true">←</span><strong>用家里库存</strong><small>已录食材，直接抵扣</small></div><div class="prepare-guide-option"><strong>补录食材</strong><span class="prepare-guide-arrow" aria-hidden="true">→</span><small>家里未录／刚买到</small></div></div>`;
      html+=needs.filter(need=>!C.ready(state,need)).map(need=>prepareRow(need,chef)).join('');
      if(done.length) html+=`<div class="section-label"><h2>已经备好了</h2><span>${done.length} 项</span></div>${done.map(need=>`<div class="ready-row">${icon('check')}<span>${esc(need.name)}${need.declared?' · 用量未记账':''}</span>${quantityLabel(need)}</div>`).join('')}`;
      const recent=state.operations.filter(op=>op.mealId===state.meal.id&&op.status==='active').at(-1);
      if(recent && chef) html+=`<button class="text-link" data-action="undo" data-id="${esc(recent.id)}">撤销最近一次准备操作</button>`;
      html+=`<p class="hint" style="margin-top:18px">没划完也可以开始做饭；未处理的食材不会自动增减库存。</p>`;
      if(chef) html+=button(icon('meal')+'开始烹饪','begin')+`<button class="cancel-meal-button" data-action="cancel-meal">这餐先不做了</button>`;
      return html;
    }
    if(status==='cooking') return html+`<div class="cooking-card">${icon('meal')}<h2>厨房里，正在发生好事</h2><p>慢慢做，热乎乎地端上桌。<br>食材消耗会在完成时记下。</p></div>`+(chef?button('做好了，记下这一餐','finish'):'<p class="hint">等主厨端菜，今天一定很好吃。</p>')+(chef?'<button class="cancel-meal-button" data-action="cancel-meal">这餐先不做了</button>':'');
    if(status==='done') {
      const record=state.records.find(row=>row.mealId===state.meal.id);
      return html+`<div class="cooking-card">${icon('heart')}<h2>又一起好好吃了一餐</h2><p>已记进做饭日历。照片可以现在拍，也可以之后补。</p></div>${record?.photo?`<img class="photo-preview" ${imageAttrs(record.photo)} alt="这餐的成品照片">`:''}<div class="button-row">${button(icon('camera')+'拍照留念','photo',`data-id="${esc(record?.id)}"`,'button-secondary')}${button('分享这一餐','share-record',`data-id="${esc(record?.id)}"`,'button-secondary')}</div>${chef?button('安排下一餐','new-meal'):''}`;
    }
    return html+`<div class="storage-note">这餐先放下了。为本餐留出的食材已恢复可用，补录的食材留在厨房。</div>`+(chef?button('重新安排一餐','new-meal'):'');
  }
  function prepareRow(need,chef) {
    const have=C.totalAvailable(state,need),remaining=C.remaining(state,need),used=C.allocations(state,need.id);
    return `<div class="swipe-shell"><div class="swipe-under" aria-hidden="true"><span>补录食材 →</span><span>← 用家里的</span></div><article class="prepare-row" data-need="${esc(need.id)}" ${chef?'data-swipe="true"':''}><div class="prepare-top"><span class="food-emoji">${foodImage(need.name,need.iconId)}</span><div><strong>${esc(need.name)}</strong><small>${esc(need.recipes.join('、'))}</small></div><span class="requirement">${remaining===null?'+':fmt(remaining)+esc(need.unit)+(need.unknown?'+':'')}</span></div><p class="stock-hint">${used?`这餐已备 <em>${fmt(used)}${esc(need.unit)}</em> · `:''}${have?`家里已记录 <em>${fmt(have)}${esc(need.unit)}</em> 可用`:'家里还没记录，不代表没有'}${need.unknown?' · 有用量未明确':''}</p>${chef?`<div class="row-actions"><button data-action="prepare" data-id="${esc(need.id)}" data-type="left">← 用家里的</button><button data-action="prepare" data-id="${esc(need.id)}" data-type="right">补录一份 →</button></div>${need.unknown?`<button class="text-link" data-action="declare" data-id="${esc(need.id)}">这项已备好，不记精确用量</button>`:''}`:''}</article></div>`;
  }
  const dayKey=date=>`${date.getFullYear()}-${String(date.getMonth()+1).padStart(2,'0')}-${String(date.getDate()).padStart(2,'0')}`;
  function cookingCalendar() {
    const year=calendarMonth.getFullYear(),month=calendarMonth.getMonth(),prefix=dayKey(calendarMonth).slice(0,7);
    const records=state.records.filter(record=>dayKey(new Date(record.at)).startsWith(prefix));
    const counts=new Map();for(const record of records){const key=dayKey(new Date(record.at));counts.set(key,(counts.get(key)||0)+1);}
    const today=dayKey(new Date()),offset=(calendarMonth.getDay()+6)%7,total=new Date(year,month+1,0).getDate();
    const visible=calendarDay?records.filter(record=>dayKey(new Date(record.at))===calendarDay):records;
    return `<section class="cooking-calendar" aria-label="做饭日历"><div class="section-label"><h2>做饭日历</h2><span>${records.length} 餐</span></div><div class="calendar-month"><button data-action="calendar-month" data-delta="-1" aria-label="上个月">‹</button><h3>${year} 年 ${month+1} 月</h3><button data-action="calendar-month" data-delta="1" aria-label="下个月">›</button></div><div class="calendar-grid"><div class="calendar-weekdays">${['一','二','三','四','五','六','日'].map(day=>`<span>${day}</span>`).join('')}</div><div class="calendar-days">${'<span class="calendar-gap" aria-hidden="true"></span>'.repeat(offset)}${Array.from({length:total},(_,i)=>{const key=dayKey(new Date(year,month,i+1)),count=counts.get(key)||0;return `<button class="calendar-day ${count?'marked':''} ${key===today?'today':''}" data-action="calendar-day" data-date="${key}" aria-label="${month+1}月${i+1}日，${count}餐" aria-pressed="${calendarDay===key}"><span>${i+1}</span><i aria-hidden="true"></i></button>`;}).join('')}</div></div><div class="calendar-record-heading"><h3>${calendarDay?`${month+1} 月 ${Number(calendarDay.slice(-2))} 日`:'本月记录'}</h3>${calendarDay?'<button data-action="calendar-clear">看整月</button>':'<small>有圆点的日子，记下了一餐</small>'}</div><div class="calendar-records">${visible.map(recordCard).join('') || `<p class="calendar-empty">${calendarDay?'这天还没有做饭记录。':'这个月还没有记录，做好一餐后就会留在这里。'}</p>`}</div></section>`;
  }
  function minePage() {
    const days=new Set(state.records.map(record=>dayKey(new Date(record.at)))).size;
    return heading('我的','LITTLE THINGS','把每一顿普通的饭，过成日子。')+`<div class="profile-card">${avatar(A.user)}<div class="profile-copy"><h2>${esc(A.user?.nickname || '本机体验')}</h2><p>${A.user?esc(A.household.name):'尚未登录 · 记录保存在本机'} · 当前是${state.role==='chef'?'主厨':'美食家'}</p></div><button class="profile-edit" data-action="${A.user?'edit-profile':'account-login'}">${A.user?'编辑':'登录'} ${icon('arrow')}</button></div>${A.user?`<p class="account-sync-note" role="status">${A.offline?'离线留档 · 家庭修改需联网':A.syncing?'正在保存到家庭…':'家庭记录已同步'}</p>`:''}<div class="profile-stats"><div><strong>${state.recipes.length}</strong><small>喜欢的菜</small></div><div><strong>${state.records.length}</strong><small>一起吃的餐</small></div><div><strong>${days}</strong><small>做饭的日子</small></div></div>${cookingCalendar()}<div class="settings-list"><button data-action="settings"><span>设置</span>${icon('arrow')}</button></div>`;
  }
  function settings() {sheet('设置',`<div class="settings-list"><button data-action="${A.user?'edit-profile':'account-login'}"><span>${A.user?'头像与昵称':'登录或注册账号'}</span>${icon('arrow')}</button><button data-action="family"><span>家庭成员与邀请</span>${icon('arrow')}</button><button data-action="resume-draft"><span>继续未完成的菜谱草稿</span>${icon('arrow')}</button><button data-action="export"><span>导出菜谱备份</span>${icon('arrow')}</button></div>${A.user?button('退出账号','account-logout','','delete-space-button'):''}`);}
  function avatar(user) {return `<div class="avatar">${safeCover(user?.avatar)?`<img ${imageAttrs(user.avatar)} alt="${esc(user.nickname)}的头像">`:esc((user?.nickname || '食').slice(0,1))}</div>`;}
  function authSheet(register=false) {
    if(!A.available){sheet('账号服务尚未连接',`<p class="sheet-note">请在完整后端页面打开应用，或刷新后再试。</p>`);return;}
    const fields=field('账号','login','','text',`required minlength="3" maxlength="40" autocomplete="username" placeholder="字母、数字或下划线"`)+field('密码','password','','password',`required minlength="8" maxlength="128" autocomplete="${register?'new-password':'current-password'}"`);
    sheet(register?'开启我们的小厨房':'欢迎回来',`<p class="sheet-note">${register?'各自的账号，同一个厨房。注册后可以邀请家人一起使用。':'登录后继续查看你们的厨房和做饭记录。'}</p><form data-form="account-${register?'register':'login'}">${register?field('昵称','nickname','','text','required maxlength="30" autocomplete="nickname" placeholder="怎么称呼你"'):''}${fields}${register?field('确认密码','confirmPassword','','password','required minlength="8" maxlength="128" autocomplete="new-password"')+'<label class="account-import"><input type="checkbox" name="importLocal" checked>保留当前本机的厨房和菜谱记录</label>':''}<p class="form-error" role="alert"></p><button type="submit" class="button-primary">${register?'注册并进入厨房':'登录'}</button></form><button class="account-switch" data-action="${register?'account-login':'account-register'}">${register?'已有账号，去登录':'还没有账号？创建一个'}</button>`);
  }
  function editProfile() {
    if(!A.user)return authSheet();profileDraft={nickname:A.user.nickname,avatar:A.user.avatar,busy:false};
    sheet('头像与昵称',form(`<div id="account-avatar-preview" class="profile-avatar-editor">${avatar(profileDraft)}</div><div class="button-row"><button type="button" class="button-secondary" data-action="avatar-upload">${icon('camera')}更换头像</button><button type="button" class="button-secondary" data-action="avatar-remove">使用默认头像</button></div><input id="account-avatar-file" type="file" accept="image/png,image/jpeg,image/webp" hidden>${field('昵称','nickname',A.user.nickname,'text','required maxlength="30" autocomplete="nickname"')}<p class="hint">账号：${esc(A.user.login)}</p>`,'account-profile'));
  }
  async function accountSubmit(element,values) {
    const submit=element.querySelector('[type="submit"]');submit.disabled=true;
    try {
      const type=element.dataset.form;
      if(type==='account-register') {
        if(values.password!==values.confirmPassword)throw Error('两次密码不一致');
        const initial=values.importLocal?snapshot():(()=>{const guest=C.seed();guest.stocks=[];guest.recipes=[];guest.records=[];const {recipes,...data}=guest;return {state:data,recipeData:{version:2,recipes,evidence:{}}};})();
        await A.authenticate('register',{login:values.login,password:values.password,nickname:values.nickname,snapshot:initial});
      } else if(type==='account-login')await A.authenticate('login',{login:values.login,password:values.password});
      else if(type==='account-profile'){if(profileDraft.busy)throw Error('头像正在处理，请稍等');await A.profile({nickname:values.nickname,avatar:profileDraft.avatar});}
      else if(type==='account-join')await A.join(values.code);
      close();
    } catch(error){element.querySelector('.form-error').textContent=error.message;}
    finally{submit.disabled=false;}
  }
  function recordCard(record) {const date=new Date(record.at);return `<button class="record-card" data-action="record" data-id="${esc(record.id)}"><div class="record-date"><strong>${date.getDate()}</strong><small>${date.getMonth()+1} 月</small></div><div><h3>${esc(record.dishes[0]?.name || '一起吃饭')}</h3><p>${record.dishes.length} 道菜 · ${record.photo?'留下了一张照片':'等一张照片，也可以只记下'}</p></div>${record.photo?`<img ${imageAttrs(record.photo)} alt="本餐照片">`:icon('arrow')}</button>`;}
  function openRecipe(card,fromMeal=false) {
    const evidence=store.resolve(card);
    sheet(card.name,`<div class="detail-title-row">${!fromMeal?`<button type="button" class="button-secondary recipe-edit-top" data-action="edit-recipe" data-id="${esc(card.id)}">编辑这道菜 ${icon('arrow')}</button>`:`<p class="sheet-note">本餐 ${fmt(card.targetServings)} 份</p>`}${recipeArt(card)}</div><div class="chips">${card.ingredients.map(row=>`<span>${esc(row.name)}${row.quantity!==null&&!row.pending?' '+fmt(row.quantity)+esc(displayUnit(row.unit)):''}</span>`).join('')}</div><ol class="detail-steps">${card.steps.map(step=>`<li>${esc(step)}</li>`).join('')}</ol>${card.id.startsWith('demo-')?'<p class="hint">演示配方，用于体验选菜和库存流程。</p>':''}${safeLink(card.source)?`<a href="${esc(card.source)}" target="_blank" rel="noopener noreferrer">查看原内容 ↗</a>`:''}${evidence.length?`<details class="source-detail"><summary>看看原始依据（${evidence.length} 项）</summary>${evidence.map(row=>`<strong>${esc(row.locator || row.kind)}</strong><p>${esc(row.text)}</p>${safeAsset(row.asset)?`<img loading="lazy" ${imageAttrs(row.asset)} alt="来源画面">`:''}`).join('')}</details>`:''}${!fromMeal&&state.meal.status==='draft'?button(state.meal.selections.some(row=>row.recipeId===card.id)?'从本餐移除':'我想吃这道','pick',`data-id="${esc(card.id)}"`):''}`);
  }
  function form(body,type,extra='') {return `<form data-form="${type}" ${extra}>${body}<p class="form-error" role="alert"></p><button type="submit" class="button-primary">确认</button></form>`;}
  function field(label,name,value='',type='text',extra='') {return `<label class="field">${label}<input name="${name}" type="${type}" value="${esc(value)}" ${extra}></label>`;}
  function selectField(label,name,choices,selected,extra='') {
    const id='select-'+C.uid(),current=choices.find(([value])=>String(value)===String(selected)) || choices[0];
    return `<div class="field select-field"><span class="field-label">${esc(label)}</span><div class="select-control"><select name="${name}" hidden aria-hidden="true" tabindex="-1" ${extra}>${choices.map(([value,text])=>`<option value="${esc(value)}" ${String(value)===String(current[0])?'selected':''}>${esc(text)}</option>`).join('')}</select><button type="button" class="select-trigger" role="combobox" aria-label="${esc(label)}" aria-expanded="false" aria-haspopup="listbox" aria-controls="${id}" data-action="select-toggle"><span class="select-value">${esc(current[1])}</span><span aria-hidden="true">⌄</span></button><div id="${id}" class="select-options" role="listbox" aria-label="${esc(label)}选项" hidden>${choices.map(([value,text])=>`<li class="select-entry"><button type="button" class="select-option" role="option" aria-selected="${String(value)===String(current[0])}" data-action="select-option" data-value="${esc(value)}"><span class="select-option-label">${esc(text)}</span><span class="select-option-check" aria-hidden="true">✓</span></button></li>`).join('')}</div></div></div>`;
  }
  function syncSelect(select) {
    const control=select.closest('.select-control');if(!control)return;
    control.querySelector('.select-value').textContent=select.selectedOptions[0]?.textContent || '';
    control.querySelectorAll('[role="option"]').forEach(option=>option.setAttribute('aria-selected',String(option.dataset.value===select.value)));
  }
  function closeSelects(except) {
    document.querySelectorAll('.select-options').forEach(options=>{if(options===except)return;options.hidden=true;options.closest('.select-control').querySelector('.select-trigger').setAttribute('aria-expanded','false');});
  }
  function locationChoices() {return [...state.spaces.flatMap(space=>space.zones.map((zone,i)=>[space.id+':'+i,space.name+' · '+zone])),['unplaced','暂不分配位置']];}
  function units(selected='克',name='unit',optional=false) {
    selected=displayUnit(selected);const values=['克','千克','个','袋','勺','毫升'];if(selected && !values.includes(selected))values.push(selected);
    return selectField('单位',name,[...(optional?[['','未指定']]:[]),...values.map(value=>[value,value])],selected);
  }
  function ingredientControl(row={},recipe=false) {
    const id=IngredientIcons.valid(row.iconId)?row.iconId:'category-other',controlId='ingredient-'+C.uid();
    return `<div class="ingredient-control"><label class="field-label" for="${controlId}">食材名称</label><div class="ingredient-name-control"><span class="selected-ingredient-icon" aria-hidden="true">${foodImage('',id)}</span><input id="${controlId}" data-ingredient-name name="${recipe?'ingredientName':'name'}" value="${esc(row.name || '')}" required maxlength="50" placeholder="选择食材，或自己填写"><input type="hidden" data-ingredient-icon name="${recipe?'ingredientIcon':'iconId'}" value="${id}"><button type="button" data-action="ingredient-toggle" aria-label="选择食材图标" aria-expanded="false" aria-controls="${controlId}-options">⌄</button></div><div class="ingredient-options" id="${controlId}-options" role="listbox" aria-label="食材图标" hidden>${IngredientIcons.items.map(item=>`<button type="button" role="option" aria-selected="${item.id===id}" data-action="ingredient-select" data-icon="${item.id}">${foodImage('',item.id)}<span>${esc(item.name)}</span></button>`).join('')}</div></div>`;
  }
  function zoneFields(layout,names=[]) {
    return `<div class="zone-name-grid ${layout}">${C.layoutZones(layout).map((position,i)=>`<label class="zone-name-cell"><span>${position}</span><input name="zone-${i}" value="${esc(names[i] || '')}" placeholder="${position}" aria-label="${position}分区名字" maxlength="30"></label>`).join('')}</div>`;
  }
  function openSpaceEditor(space) {
    const layout=space?.layout || 'four';
    sheet(space?'空间设置':'再添一个储物空间',form(field('空间名字','name',space?.name || '','text','required maxlength="30"')+(space?'':selectField('类型','type',[['fridge','冰箱'],['cupboard','橱柜']],'fridge'))+selectField('布局','layout',[['four','四格'],['two','上下两层'],['horizontal','左右两侧']],layout,'data-layout-select')+`<p class="field-label">给每个位置起个名字</p><div id="zone-name-editor">${zoneFields(layout,space?.zones)}</div>${space?'<p class="hint">减少分区时，多出的食材会移到最后一个分区。</p>':''}`,space?'layout':'add-space',space?`data-id="${esc(space.id)}"`:'')+(space?button('删除这个储物空间','delete-space',`data-id="${esc(space.id)}"`,'delete-space-button'):''));
  }
  function confirmDeleteSpace(id) {
    const space=state.spaces.find(row=>row.id===id);if(!space)throw Error('找不到这个储物空间');
    const count=state.stocks.filter(row=>row.space===id).length;
    sheet('删除这个储物空间？',`<p class="sheet-note">将删除「${esc(space.name)}」。${count?`里面的${count}项食材会移到“还没安顿的食材”，数量和本餐预留都会保留。`:'这个空间里没有食材。'}</p>${button('保留这个空间','layout',`data-id="${esc(id)}"`,'button-secondary')}${button('确认删除','confirm-delete-space',`data-id="${esc(id)}"`,'delete-space-button')}`);
  }
  function openStock(stock,origin) {
    const left=C.available(state,stock),reserved=C.reserved(state,stock.id);
    sheet(stock.name,`${origin?`<button class="text-link" data-action="zone-stocks" data-space="${esc(origin.space)}" data-zone="${origin.zone}">← 返回本层清单</button>`:''}<div class="stock-location-row"><p class="sheet-note">${esc(location(stock))}</p><button type="button" class="text-link" data-action="move-stock" data-id="${esc(stock.id)}">移动位置 ${icon('arrow')}</button></div><div class="quantity-large">${fmt(left)}<small>${esc(displayUnit(stock.unit))}可用</small></div>${reserved?`<p class="hint">另有 ${fmt(reserved)}${esc(displayUnit(stock.unit))}留给本餐，完成时记为消耗。</p>`:''}<div class="button-row">${button('补充一些','stock-add',`data-id="${esc(stock.id)}"`,'button-secondary')}${button('日常减少','stock-reduce',`data-id="${esc(stock.id)}"`,'button-secondary')}</div>`);
  }
  function openAddStock(spaceId,zone=0,stock) {
    const space=state.spaces.find(row=>row.id===spaceId) || state.spaces[state.spaceIndex];
    sheet('给厨房添一点',form(ingredientControl(stock)+`<div class="field-row">${field('增加多少','quantity','','number','min="0.01" step="any" required inputmode="decimal"')}${units(stock?.unit || '克')}</div>`+selectField('放在哪里','location',locationChoices(),!space || stock && !stock.space?'unplaced':space.id+':'+zone),'add-stock'));
  }
  function openPrepare(id,type) {
    const need=state.meal.needs.find(row=>row.id===id);if(!need) throw Error('找不到食材');
    if(type==='left' && need.required===null) {sheet('这项用量没有写明',`<p class="sheet-note">可以标记已备好，系统不会猜数量扣库存。实际用了多少，也可以在厨房里手动记下。</p>${button('已经备好','declare',`data-id="${esc(id)}"`)}`);return;}
    const left=C.remaining(state,need),have=C.totalAvailable(state,need);
    const preset=type==='left'?Math.min(left,have):left;
    sheet(type==='left'?'用家里已经记录的':'补录这一份食材',`<p class="sheet-note">${esc(need.name)} · ${left===null?'本餐用量未明确':'本餐还差 '+fmt(left)+esc(need.unit)}<br>${type==='left'?'厨房已记录 '+fmt(have)+esc(need.unit)+'可用。':'家里已有但没录过，或刚买到，都可以在这里录入。多出的部分会留在厨房。'}${need.unknown?'<br>不明确的用量不自动扣库存，可以另标记已备好。':''}</p>`+form(`<div class="field-row">${field(type==='left'?'本餐使用量':'本次补录总量','quantity',preset || '','number','min="0.01" step="any" required inputmode="decimal"')}${type==='right'?units(need.unit || '克'):`<label class="field">单位<input value="${esc(need.unit)}" disabled></label>`}</div>`,'prepare',`data-id="${esc(id)}" data-type="${type}"`));
  }
  function editRecipe(card) {
    recipeDraft={card,coverImage:safeCover(card?.coverImage),coverBusy:false};
    sheet(card?'编辑这道菜':'手写一道喜欢的菜',form(`<div id="recipe-cover-preview">${coverEditor()}</div><input id="recipe-cover-file" type="file" accept="image/*" hidden>`+field('菜名','name',card?.name || '','text','required maxlength="100"')+`<div class="ingredient-section-heading"><h3>食材</h3><span>用量不确定可留空</span></div><div id="recipe-ingredient-rows">${(card?.ingredients || [{}]).map((row,i)=>ingredientRow(row,card?i:-1)).join('')}</div><button type="button" class="add-ingredient-button" data-action="ingredient-add">${icon('plus')}添加一种食材</button><div class="ingredient-section-heading"><h3>制作步骤</h3></div><div id="recipe-step-rows">${(card?.steps.length?card.steps:['']).map(stepRow).join('')}</div><button type="button" class="add-ingredient-button" data-action="step-add">${icon('plus')}添加一步</button>`,'recipe',card?`data-id="${esc(card.id)}"`:''));
  }
  const draftOwner=()=>A.user?.id || 'guest';
  function saveRecipeDraft() {
    const form=$('sheet-body').querySelector('[data-form="recipe"]');if(!form || !window.LocalCache)return;
    const ingredients=[...form.querySelectorAll('.recipe-ingredient-row')].map(row=>({name:row.querySelector('[data-ingredient-name]').value,iconId:row.querySelector('[data-ingredient-icon]').value,quantity:row.querySelector('[name="ingredientQuantity"]').value,unit:row.querySelector('[name="ingredientUnit"]').value,originalIndex:Number(row.dataset.originalIndex)}));
    const steps=[...form.querySelectorAll('[name="recipeStep"]')].map(row=>row.value);
    return window.LocalCache.saveDraft(draftOwner(),{card:recipeDraft?.card || null,coverImage:recipeDraft?.coverImage || '',name:form.elements.name.value,ingredients,steps}).catch(()=>toast('草稿留档失败，请先复制重要内容'));
  }
  async function resumeRecipeDraft() {
    const draft=await window.LocalCache?.readDraft(draftOwner());if(!draft){toast('目前没有未完成的菜谱草稿');return;}
    editRecipe(draft.card || undefined);recipeDraft.coverImage=draft.coverImage;
    const form=$('sheet-body').querySelector('form');form.elements.name.value=draft.name;
    $('recipe-ingredient-rows').innerHTML=draft.ingredients.map(row=>ingredientRow(row,row.originalIndex)).join('');
    $('recipe-step-rows').innerHTML=draft.steps.map(stepRow).join('');$('recipe-cover-preview').innerHTML=coverEditor();
  }
  function stepRow(text,index) {return `<section class="recipe-step-row"><div class="ingredient-row-heading"><label class="step-number" for="step-${index}">第 ${index+1} 步</label><button type="button" data-action="step-remove" aria-label="删除第${index+1}步">×</button></div><textarea id="step-${index}" name="recipeStep" rows="3" aria-label="第${index+1}步" placeholder="这一步要怎么做…">${esc(text)}</textarea></section>`;}
  function numberSteps() {$('recipe-step-rows').querySelectorAll('.recipe-step-row').forEach((row,i)=>{const label=row.querySelector('.step-number'),input=row.querySelector('textarea');label.textContent=`第 ${i+1} 步`;label.htmlFor=input.id='step-'+i;input.setAttribute('aria-label',`第${i+1}步`);row.querySelector('button').setAttribute('aria-label',`删除第${i+1}步`);});}
  function ingredientRow(row={},originalIndex=-1) {
    return `<section class="recipe-ingredient-row" data-original-index="${originalIndex}"><div class="ingredient-row-heading"><span>一种食材</span><button type="button" data-action="ingredient-remove" aria-label="删除这项食材">×</button></div>${ingredientControl(row,true)}<div class="field-row">${field('用量','ingredientQuantity',row.quantity??'','number','min="0" step="any" inputmode="decimal" placeholder="可留空"')}${units(row.unit || '','ingredientUnit',true)}</div></section>`;
  }
  function coverEditor() {
    const photo=recipeDraft.coverImage,src=photo || (recipeDraft.card?coverUrl({...recipeDraft.card,coverImage:null}):'/assets/dishes/v1/256/default-dish.png');
    return `<div class="recipe-cover-editor"><img class="${photo || !src.startsWith('/assets/dishes/')?'':'dish-illustration'}" ${imageAttrs(src)} alt="菜谱封面预览"><div><strong>成品菜封面</strong><p>${recipeDraft.coverBusy?'正在处理图片…':photo?'使用你上传的照片':'没有照片时显示成品菜插画或来源图片'}</p><button type="button" data-action="recipe-cover-upload">${icon('camera')}${photo?'更换照片':'上传照片'}</button>${photo?'<button type="button" class="cover-remove" data-action="recipe-cover-remove">移除照片</button>':''}</div></div>`;
  }
  async function uploadRecipeCover(file,formElement) {
    const draft=recipeDraft;if(!file || !draft)return;let url;
    draft.coverBusy=true;
    const refresh=()=>{if(recipeDraft===draft && formElement.isConnected){$('recipe-cover-preview').innerHTML=coverEditor();formElement.querySelector('[type="submit"]').disabled=draft.coverBusy;}};
    refresh();
    try {
      if(!file.type.startsWith('image/'))throw Error('请选择图片');
      url=URL.createObjectURL(file);const image=new Image();image.src=url;await image.decode();
      if(!image.naturalWidth || !image.naturalHeight)throw Error('图片无法读取');
      const scale=Math.min(1,1000/Math.max(image.naturalWidth,image.naturalHeight)),canvas=document.createElement('canvas');canvas.width=Math.max(1,Math.round(image.naturalWidth*scale));canvas.height=Math.max(1,Math.round(image.naturalHeight*scale));
      const context=canvas.getContext('2d');context.fillStyle='#f8faf2';context.fillRect(0,0,canvas.width,canvas.height);context.drawImage(image,0,0,canvas.width,canvas.height);
      const photo=canvas.toDataURL('image/jpeg',.78);if(!safeCover(photo))throw Error('图片过大，请换一张');
      draft.coverImage=photo;
    } catch(error) {if(formElement.isConnected)formElement.querySelector('.form-error').textContent=error.message || '图片读取失败';}
    finally {draft.coverBusy=false;refresh();if(url)URL.revokeObjectURL(url);void saveRecipeDraft();}
  }
  function randomSheet(reroll=false) {
    if(state.meal.status!=='draft') throw Error('本餐菜单已固定');
    if(!reroll) {randomLocked=[];randomRows=C.sample(state.recipes,randomCount);}
    sheet('把选择交给一点运气',`<p class="sheet-note">从收藏里挑。喜欢哪道就锁住，再换其余的。</p>${selectField('这餐选几道','randomCount',[1,2,3,4,5,6].map(count=>[String(count),count+' 道']),String(randomCount),'id="random-count"')}${randomRows.map(card=>`<div class="random-choice"><span>${dishImage(card)}</span><div><strong>${esc(card.name)}</strong><small>${randomLocked.includes(card.id)?'留下这道':'可以再换换'}</small></div><button class="${randomLocked.includes(card.id)?'locked':''}" data-action="random-lock" data-id="${esc(card.id)}" aria-label="${randomLocked.includes(card.id)?'解锁':'锁住'}${esc(card.name)}" aria-pressed="${randomLocked.includes(card.id)}">${icon('lock')}</button></div>`).join('')}<div class="button-row">${button(icon('dice')+'换其余的','reroll','','button-secondary')}${button('这些加入本餐','random-add')}</div>${randomCount>state.recipes.length?'<p class="hint">收藏还没有那么多，先把现有的都选上。</p>':''}`);
  }
  function ideas() {
    const names=new Set(state.stocks.filter(stock=>C.available(state,stock)>0).map(stock=>C.foodName(stock.name)));
    const candidates=state.recipes.map(card=>({card,matched:card.ingredients.filter(row=>names.has(C.foodName(row.name))).length})).filter(row=>row.matched>0).sort((a,b)=>b.matched-a.matched).slice(0,4);
    sheet('家里的食材，可以想一餐',`${button('让 AI 想一道新菜','generate-ingredients','','button-secondary')}<p class="sheet-note">这轮先从已收藏菜谱里匹配食材。库存不完整也没关系，选好后再准备。也可以让 AI 用已有食材创作新菜。</p>${candidates.map(({card,matched})=>`<p class="hint">${matched} 种食材家里已有记录</p>${recipeCard(card)}`).join('') || '<p class="hint">还没找到合适的收藏，先添一道菜谱，或补录一些食材。</p>'}`);
  }
  function family() {
    if(!A.user)return authSheet();
    sheet('我们在同一个家庭',`<p class="sheet-note">${esc(A.household.name)} · ${A.members.length}位成员<br>各自登录账号，一起管理同一个厨房。</p>${A.members.map(member=>`<div class="member-row">${avatar(member)}<span>${esc(member.nickname)}${member.id===A.user.id?' · 我':''}</span><small>家庭成员</small></div>`).join('')}<p class="section-label">家庭邀请码</p><div class="invite-code">${esc(A.household.invite)}</div>${button('复制邀请码','copy-invite','','button-secondary')}<p class="hint">把邀请码发给家人，让对方注册自己的账号后加入。</p>${button('加入另一个家庭','join-family','','button-secondary')}`);
  }
  function showRecord(record) {sheet('这一餐，值得留念',`<p class="sheet-note">${new Date(record.at).toLocaleString('zh-CN')} · ${record.dishes.length} 道菜</p><div class="chips">${record.dishes.map(dish=>`<span>${esc(dish.name)}</span>`).join('')}</div>${record.photo?`<img class="photo-preview" ${imageAttrs(record.photo)} alt="这一餐成品照片">`:'<p class="sheet-note">没拍照片也没关系，这一餐已经记下了。</p>'}${record.unrecorded.length?'<p class="hint">这餐有部分用量未记录，相关库存未自动扣减。</p>':''}<div class="button-row">${button(icon('camera')+'拍照留念','photo',`data-id="${esc(record.id)}"`,'button-secondary')}${button('生成分享卡','share-record',`data-id="${esc(record.id)}"`,'button-secondary')}</div>`);}
  async function makeMenuCard(dishes,record) {
    let photo=null;
    if(record?.photo) {photo=new Image();photo.src=window.PrivateAssets?.valid(record.photo)?await PrivateAssets.load(record.photo):record.photo;if(!photo.src)throw Error('照片尚未下载，请联网打开后再试');await photo.decode();}
    const offset=photo?405:0;
    const canvas=document.createElement('canvas');canvas.width=750;canvas.height=390+dishes.length*86+offset;const ctx=canvas.getContext('2d');
    ctx.fillStyle='#f8f6ef';ctx.fillRect(0,0,canvas.width,canvas.height);ctx.strokeStyle='#bac7ad';ctx.lineWidth=2;ctx.strokeRect(25,25,700,canvas.height-50);
    ctx.fillStyle='#365b46';ctx.font='34px serif';ctx.fillText('一起吃饭',65,100);ctx.font='58px serif';ctx.fillText(record?'这一餐的烟火':'今天这一餐',65,190);
    ctx.font='19px sans-serif';ctx.fillStyle='#8d9581';ctx.fillText(record?new Date(record.at).toLocaleDateString('zh-CN'):new Date().toLocaleDateString('zh-CN'),65,240);
    if(photo){const scale=Math.min(620/photo.naturalWidth,350/photo.naturalHeight),width=photo.naturalWidth*scale,height=photo.naturalHeight*scale;ctx.drawImage(photo,65+(620-width)/2,275+(350-height)/2,width,height);}
    dishes.forEach((dish,index)=>{const y=315+offset+index*86;ctx.fillStyle='#c86d45';ctx.font='20px serif';ctx.fillText(String(index+1).padStart(2,'0'),65,y);ctx.fillStyle='#273e34';ctx.font='31px serif';ctx.fillText(dish.name,112,y,550);ctx.strokeStyle='#e1e4d6';ctx.beginPath();ctx.moveTo(65,y+29);ctx.lineTo(685,y+29);ctx.stroke();});
    ctx.font='20px serif';ctx.fillStyle='#89967e';ctx.fillText('好好吃饭，也好好在一起。',65,canvas.height-65);return canvas.toDataURL('image/png');
  }
  let shareImage='';
  function shareMenu(record) {
    const dishes=record?.dishes || (state.meal.status==='draft'?C.draftDishes(state):state.meal.dishes);if(!dishes.length) throw Error('先选好这一餐的菜');
    makeMenuCard(dishes,record).then(image=>{shareImage=image;sheet(record?'分享这一餐':'分享本餐菜单',`<p class="sheet-note">${record?.photo?'成品照片、':''}菜单与日期，保存后可以发给喜欢的人。</p><img class="share-preview" src="${shareImage}" alt="可保存的菜单分享卡">${button('保存菜单图片','download-share')}`);}).catch(error=>toast('分享卡生成失败，请重试或更换照片。'));
  }
  function importSheet() {if(A.available && !A.user)return authSheet();sheet('把链接变成一道菜',`<p class="sheet-note">粘贴分享文本或链接，生成后在这里核对并确认收藏。</p><form data-form="parse"><label class="field">链接或分享文本<textarea name="share" rows="4" required placeholder="粘贴想做的那道菜…"></textarea></label><details><summary class="hint">也可以补充原帖正文</summary><label class="field">补充正文<textarea name="article" rows="3"></textarea></label></details><p class="form-error" role="alert"></p><button class="button-primary">生成菜谱卡</button></form>`);}
  function generationSheet(kind) {
    if(!A.user)return authSheet();
    if(A.offline)throw Error('生成菜谱需要联网');
    const title=kind==='image'?'识别菜谱图片':kind==='ingredients'?'用家里的食材想一道菜':'说说你想做什么';
    const input=kind==='image'?'<label class="field">菜谱图片<input name="image" type="file" accept="image/jpeg,image/png,image/webp" required></label>':kind==='ingredients'?`<label class="field">已有食材<textarea name="ingredients" rows="3" required>${esc(state.stocks.filter(row=>C.available(state,row)>0).map(row=>row.name).join('、'))}</textarea></label>`:'';
    sheet(title,`<p class="sheet-note">${kind==='image'?'识别图片中的食材和做法文字，完成后在这里核对并收藏。':'生成建议后，在这里核对食材和做法，再确认收藏。'}</p><form data-form="generate" data-kind="${kind}">${input}<label class="field">${kind==='text'?'想做什么':'补充要求（可选）'}<textarea name="prompt" rows="3" ${kind==='text'?'required':''} placeholder="例如：两个人的家常晚饭，少辣…"></textarea></label><p class="form-error" role="alert"></p><button class="button-primary">开始生成</button></form>`);
  }
  const jobStatus=value=>({queued:'等待处理',running:'正在处理',succeeded:'已完成',failed:'需要重试',cancelled:'已取消'})[value] || value;
  async function showJobs() {
    if(!A.user)return authSheet();
    const version=sheetVersion,account=A.user.id,family=A.household?.id;
    const {jobs}=await JobsClient.list();
    if(sheetVersion!==version || A.user?.id!==account || A.household?.id!==family)return;
    sheet('生成记录',`<p class="sheet-note">关闭弹窗后，生成仍会继续。可以在这里打开之前的菜谱，核对后收藏。</p><div class="settings-list">${jobs.map(job=>`<button data-action="job-detail" data-id="${esc(job.id)}"><span>${esc(({link:'链接整理',image:'图片识别',text:'文字创作',ingredients:'食材想菜'})[job.kind])}<small> · ${esc(jobStatus(job.status))}</small></span>${icon('arrow')}</button>`).join('') || '<p class="hint">还没有生成记录。</p>'}</div>`);
  }
  function jobOutput(job) {
    const events=job.events || [],evidence=job.result?.evidence?.length?job.result.evidence:events.filter(row=>row.type==='source').flatMap(row=>row.evidence || []);
    const rows=job.result?.recipes?.length?job.result.recipes:events.filter(row=>row.type==='recipes').flatMap(row=>row.recipes || []);
    return {evidence,cards:[...new Map(rows.map(row=>[row.id || JSON.stringify([row.name,row.source]),row])).values()]};
  }
  function presentJob(job,fetchError='') {
    const {cards}=jobOutput(job),busy=['queued','running'].includes(job.status),saved=cards.length && cards.every(card=>state.recipes.some(row=>row.id===card.id));
    const progress=(job.events || []).filter(row=>row.type==='progress' && row.message).at(-1)?.message || jobStatus(job.status);
    latestJob=saved?null:{id:job.id,status:job.status};
    const body=`<div class="generation-progress ${busy?'is-running':''}" role="status"><span class="generation-dot"></span><div><strong>${busy?esc(progress):saved?'已在你的菜谱里':cards.length?`已整理 ${cards.length} 道菜`:'这次还没有整理出菜谱'}</strong><p>${busy?'可以留在这里等待，关闭弹窗后也会继续处理。':cards.length?'确认食材和做法后，就会加入你的菜谱。':''}</p></div></div>${fetchError || job.error?`<p class="form-error" role="alert">${esc(fetchError || job.error)}</p>`:''}${(job.result?.warnings || []).map(row=>`<p class="hint">${esc(row)}</p>`).join('')}<div class="generated-recipes">${cards.map(card=>`<article class="generated-recipe"><div class="generated-recipe-heading"><img src="/assets/dishes/v1/256/default-dish.png" width="52" height="52" alt=""><h3>${esc(card.name)}</h3></div><div class="chips">${(card.ingredients || []).map(row=>`<span>${esc(row.name)}${row.quantity==null?'':` ${fmt(row.quantity)}${esc(displayUnit(row.unit))}`}</span>`).join('')}</div><ol>${(card.steps || []).map(step=>`<li>${esc(step)}</li>`).join('')}</ol></article>`).join('')}</div><div class="generation-actions">${cards.length && !busy && !saved?button(`确认收藏 · ${cards.length}道菜`,'job-save',`data-id="${esc(job.id)}"`):''}${busy?button('稍后再看','close','','button-secondary'):''}${job.status==='failed' && job.id!==localJob?.id?button('重新生成','job-retry',`data-id="${esc(job.id)}"`,'button-secondary'):''}${busy || fetchError?button('刷新进度','job-detail',`data-id="${esc(job.id)}"`,'text-link'):''}${!busy && !cards.length?'<p class="hint">可以重新添加链接、补充正文，或换一张有做法文字的图片。</p>':''}</div>`;
    sheet(busy?'正在整理菜谱':cards.length?'确认菜谱':'添加菜谱',body,job.id);
    render();
  }
  function watchJob(job) {
    const review={id:job.id,account:A.user?.id,family:A.household?.id,signature:JSON.stringify(job)};activeReview=review;
    if(job.id===localJob?.id || !['queued','running'].includes(job.status))return;
    const poll=async()=>{
      if(activeReview!==review || !$('sheet').open)return;
      try {
        const next=await JobsClient.get(review.id);
        if(activeReview!==review || A.user?.id!==review.account || A.household?.id!==review.family)return;
        const signature=JSON.stringify(next);if(signature!==review.signature){presentJob(next);review.signature=signature;}
        if(!['queued','running'].includes(next.status))return;
      } catch(error) {if(activeReview!==review)return;const target=$('sheet-body').querySelector('.generation-progress p');if(target)target.textContent='暂时无法更新进度，可以刷新或联网后在生成记录中查看。';}
      if(activeReview===review)reviewTimer=setTimeout(poll,2000);
    };
    reviewTimer=setTimeout(poll,1500);
  }
  async function showJob(id) {
    const version=sheetVersion,account=A.user?.id,family=A.household?.id,job=id===localJob?.id?localJob:await JobsClient.get(id);
    if(version!==sheetVersion || A.user?.id!==account || A.household?.id!==family)return;
    clearTimeout(reviewTimer);presentJob(job);watchJob(job);
  }
  async function beginJob(kind,input,version=sheetVersion) {
    const account=A.user?.id,family=A.household?.id,job=await JobsClient.create(kind,input);
    if(A.user?.id!==account || A.household?.id!==family)throw Error('账号或家庭已切换，请在原家庭查看生成记录');
    latestJob={id:job.id,status:job.status};render();
    if(sheetVersion===version && $('sheet').open){presentJob(job);watchJob(job);}
  }
  async function saveJob(id) {
    if(savingJobs.has(id))return;savingJobs.add(id);
    const account=A.user?.id,family=A.household?.id;
    const submit=$('sheet-body').querySelector('[data-action="job-save"]');if(submit)submit.disabled=true;
    try {
    const job=id===localJob?.id?localJob:await JobsClient.get(id),{evidence:source,cards}=jobOutput(job);
    if(['queued','running'].includes(job.status))throw Error('菜谱还在整理，请完成后确认收藏');
    let count=0;
    for(const raw of cards) {
      if(A.user?.id!==account || A.household?.id!==family)throw Error('账号或家庭已切换，请重新打开任务');
      if(state.recipes.some(row=>row.id===raw.id))continue;
      store.register(source);const card=oneRecipe(store.normalize(raw));
      await mutate('recipe.upsert',{recipe:card,evidence:Object.fromEntries(store.resolve(card).map(row=>[row.id,row]))},()=>state.recipes.unshift(card));count++;
      rememberReal(card);
    }
    latestJob=null;close();transact(()=>{state.page='recipes';},false);
    } finally {savingJobs.delete(id);if(submit)submit.disabled=false;}
  }
  async function parseRecipes(body) {
    if(parseBusy) return;
    const account=A.user?.id,family=A.household?.id,version=sheetVersion;
    parseBusy=true;
    try {
      if(A.user){await beginJob('link',body,version);return;}
      const job={id:'local-'+C.uid(),kind:'link',status:'running',result:{},events:[]};localJob=job;presentJob(job);watchJob(job);
      const consume=async event=>{
        if(A.user?.id!==account || A.household?.id!==family)throw Error('账号或家庭已切换，任务仍保留在原家庭');
        job.events.push(event);
        if(event.type==='done'){job.status='succeeded';job.result.warnings=event.warnings || [];}
        latestJob={id:job.id,status:job.status};
        if(activeReview?.id===job.id && $('sheet').open)presentJob(job);else render();
      };
      try{await RecipeStream.generate(body,consume);}catch(error){job.status='failed';job.error=error.message;if(activeReview?.id===job.id && A.user?.id===account)presentJob(job);}
    } finally {parseBusy=false;const submit=$('sheet-body').querySelector('[data-form="parse"] .button-primary');if(submit)submit.disabled=false;render();}
  }
  document.addEventListener('click',async event=>{
    if(!event.target.closest('.select-control'))closeSelects();
    if(!event.target.closest('.ingredient-control'))document.querySelectorAll('.ingredient-options').forEach(row=>{row.hidden=true;row.closest('.ingredient-control').querySelector('[data-action="ingredient-toggle"]').setAttribute('aria-expanded','false');});
    const target=event.target.closest('[data-action]');if(!target || target.disabled || Date.now()-lastSwipe<250) return;
    const d=target.dataset;
    if(!A.ready){toast('正在检查登录状态，请稍等');return;}
    if(A.syncing && !['nav','role','space','close','recipe','stock','zone-stocks','settings','family','copy-invite'].includes(d.action)){toast('正在保存到家庭，请稍等');return;}
    if(state.meal.status!=='draft' && ['pick','random'].includes(d.action)) {
      toast('本餐菜单已固定，暂无法点菜',null,2400);return;
    }
    try {
      let pending;
      switch(d.action) {
        case 'close':close();break;
        case 'jobs':await showJobs();break;
        case 'job-detail':await showJob(d.id);break;
        case 'job-save':await saveJob(d.id);break;
        case 'job-retry':await JobsClient.action(d.id,'retry');await showJob(d.id);break;
        case 'job-cancel':await JobsClient.action(d.id,'cancel');await showJob(d.id);break;
        case 'generate-image':generationSheet('image');break;
        case 'generate-text':generationSheet('text');break;
        case 'generate-ingredients':generationSheet('ingredients');break;
        case 'nav':transact(()=>{state.page=d.page;},false);window.scrollTo({top:0,behavior:'instant'});break;
        case 'role':transact(()=>{state.role=d.role;if(state.page==='kitchen'&&d.role==='foodie')state.page='recipes';},false);break;
        case 'space':transact(()=>{state.spaceIndex=Number(d.index);},false);break;
        case 'account-login':authSheet();break;
        case 'retry-sync':await A.retryPending();break;
        case 'account-register':authSheet(true);break;
        case 'edit-profile':editProfile();break;
        case 'avatar-upload':$('account-avatar-file').click();break;
        case 'avatar-remove':profileDraft.avatar='';$('account-avatar-preview').innerHTML=avatar(profileDraft);break;
        case 'account-logout':sheet('退出当前账号？',`<p class="sheet-note">家庭记录会保留，重新登录后可以继续使用。</p>${button('继续使用','settings','','button-secondary')}${button('确认退出','confirm-logout','','delete-space-button')}`);break;
        case 'confirm-logout':void (A.offline && window.NativeBridge?.native()?A.disconnectLocal():A.logout()).then(()=>authSheet()).catch(error=>toast(error.message));break;
        case 'copy-invite':void navigator.clipboard.writeText(A.household.invite).then(()=>toast('邀请码已复制')).catch(()=>toast('邀请码：'+A.household.invite));break;
        case 'stock':openStock(state.stocks.find(row=>row.id===d.id),d.originSpace?{space:d.originSpace,zone:Number(d.originZone)}:null);break;
        case 'zone-stocks':openZoneStocks(d.space,Number(d.zone));break;
        case 'add-stock':openAddStock(d.space,Number(d.zone || 0));break;
        case 'stock-add':{const stock=state.stocks.find(row=>row.id===d.id);openAddStock(stock.space,stock.zone,stock);break;}
        case 'stock-reduce':{const stock=state.stocks.find(row=>row.id===d.id);sheet('记下日常用掉的',`<p class="sheet-note">${esc(stock.name)} · 可用 ${fmt(C.available(state,stock))}${esc(stock.unit)}<br>用于本餐的食材，请在“这一餐”里左滑，避免重复扣除。</p>`+form(field('减少多少（'+stock.unit+'）','quantity','','number','min="0.01" step="any" required'),'reduce-stock',`data-id="${esc(d.id)}"`));break;}
        case 'move-stock':{const stock=state.stocks.find(row=>row.id===d.id);sheet('移动'+stock.name,form(`<p class="sheet-note">现在放在：${esc(location(stock))}</p>`+selectField('储物位置','location',locationChoices(),stock.space?stock.space+':'+stock.zone:'unplaced'),'move-stock',`data-id="${esc(d.id)}"`));break;}
        case 'add-space':openSpaceEditor();break;
        case 'layout':openSpaceEditor(d.id?state.spaces.find(row=>row.id===d.id):state.spaces[state.spaceIndex]);break;
        case 'delete-space':confirmDeleteSpace(d.id);break;
        case 'confirm-delete-space':pending=mutate('space.delete',{spaceId:d.id},()=>C.deleteSpace(state,d.id));if(pending?.then)await pending;close();break;
        case 'select-toggle':{event.preventDefault();const control=target.closest('.select-control'),options=control.querySelector('.select-options'),opening=options.hidden;closeSelects();options.hidden=!opening;target.setAttribute('aria-expanded',String(opening));if(opening)options.querySelector('[aria-selected="true"]').focus();break;}
        case 'select-option':{event.preventDefault();const control=target.closest('.select-control'),select=control.querySelector('select'),trigger=control.querySelector('.select-trigger');select.value=d.value;closeSelects();syncSelect(select);trigger.focus();select.dispatchEvent(new Event('change',{bubbles:true}));break;}
        case 'ingredient-toggle':{const control=target.closest('.ingredient-control'),options=control.querySelector('.ingredient-options'),opening=options.hidden;document.querySelectorAll('.ingredient-options').forEach(row=>{row.hidden=true;row.closest('.ingredient-control').querySelector('[data-action="ingredient-toggle"]').setAttribute('aria-expanded','false');});options.hidden=!opening;target.setAttribute('aria-expanded',String(opening));if(opening){const initial=control.querySelector('[data-ingredient-icon]').value==='category-other';options.querySelector(initial?'[role="option"]':'[aria-selected="true"]').focus();}break;}
        case 'ingredient-select':{const item=IngredientIcons.items.find(row=>row.id===d.icon);if(!item)break;const control=target.closest('.ingredient-control');control.querySelector('[data-ingredient-icon]').value=item.id;control.querySelector('[data-ingredient-name]').value=item.name;control.querySelector('.selected-ingredient-icon').innerHTML=foodImage('',item.id);control.querySelectorAll('[role="option"]').forEach(row=>row.setAttribute('aria-selected',String(row===target)));control.querySelector('.ingredient-options').hidden=true;control.querySelector('[data-action="ingredient-toggle"]').setAttribute('aria-expanded','false');control.querySelector('[data-ingredient-name]').focus();void saveRecipeDraft();break;}
        case 'ingredient-add':$('recipe-ingredient-rows').insertAdjacentHTML('beforeend',ingredientRow());$('recipe-ingredient-rows').lastElementChild.querySelector('[data-ingredient-name]').focus();void saveRecipeDraft();break;
        case 'ingredient-remove':target.closest('.recipe-ingredient-row').remove();void saveRecipeDraft();break;
        case 'step-add':$('recipe-step-rows').insertAdjacentHTML('beforeend',stepRow('',$('recipe-step-rows').children.length));$('recipe-step-rows').lastElementChild.querySelector('textarea').focus();void saveRecipeDraft();break;
        case 'step-remove':{const rows=$('recipe-step-rows');if(rows.children.length===1){rows.querySelector('textarea').value='';rows.querySelector('textarea').focus();}else{target.closest('.recipe-step-row').remove();numberSteps();}void saveRecipeDraft();break;}
        case 'recipe-cover-upload':$('recipe-cover-file').click();break;
        case 'recipe-cover-remove':recipeDraft.coverImage='';$('recipe-cover-preview').innerHTML=coverEditor();void saveRecipeDraft();break;
        case 'recipe':openRecipe(state.recipes.find(row=>row.id===d.id));break;
        case 'meal-recipe':openRecipe(state.meal.dishes.find(row=>row.id===d.id),true);break;
        case 'pick':pending=mutate('meal.pick',{recipeId:d.id,selected:!state.meal.selections.some(row=>row.recipeId===d.id)},()=>C.toggleDish(state,d.id));if(pending?.then)await pending;if($('sheet').open)close();break;
        case 'servings':{const row=state.meal.selections.find(row=>row.recipeId===d.id),servings=Math.max(0.5,row.servings+Number(d.delta));pending=mutate('meal.servings',{recipeId:d.id,servings},()=>C.setServings(state,d.id,servings));if(pending?.then)await pending;break;}
        case 'lock':pending=mutate('meal.lock',{},()=>C.lock(state));if(pending?.then)await pending;break;
        case 'prepare':openPrepare(d.id,d.type);break;
        case 'declare':pending=mutate('meal.declare',{needId:d.id},()=>C.declare(state,d.id));if(pending?.then)await pending;close();break;
        case 'undo':pending=mutate('meal.undo',{operationId:d.id},()=>C.undo(state,d.id));if(pending?.then)await pending;break;
        case 'begin':pending=mutate('meal.begin',{},()=>C.begin(state));if(pending?.then)await pending;break;
        case 'finish':pending=mutate('meal.finish',{},()=>C.finish(state));if(pending?.then)await pending;break;
        case 'new-meal':pending=mutate('meal.new',{},()=>C.newMeal(state));if(pending?.then)await pending;break;
        case 'cancel-meal':sheet('这餐先不做了？',`<p class="sheet-note">留给这餐的食材会恢复可用，已经补录的食材仍留在厨房。</p>${button('确认取消这一餐','confirm-cancel','','button-secondary orange')}`);break;
        case 'confirm-cancel':pending=mutate('meal.cancel',{},()=>C.cancel(state));if(pending?.then)await pending;close();break;
        case 'random':randomSheet();break;
        case 'random-lock':randomLocked=randomLocked.includes(d.id)?randomLocked.filter(id=>id!==d.id):[...randomLocked,d.id];randomSheet(true);break;
        case 'reroll':randomRows=C.sample(state.recipes,randomCount,randomLocked);randomSheet(true);break;
        case 'random-add':{const ids=randomRows.map(card=>card.id);pending=mutate('meal.select',{recipeIds:ids},()=>{for(const card of randomRows)if(!state.meal.selections.some(row=>row.recipeId===card.id))C.toggleDish(state,card.id);});if(pending?.then)await pending;transact(()=>{state.page='meal';},false);close();break;}
        case 'ideas':ideas();break;
        case 'add-recipe':sheet('收藏一个新味道',`<div class="entry-list"><button data-action="import"><span class="entry-symbol">↗</span><span><strong>贴一个分享链接</strong><small>把刷到的美食，变成菜谱</small></span>${icon('arrow')}</button><button data-action="generate-image"><span class="entry-symbol">▧</span><span><strong>发一张菜谱图片</strong><small>识别图片中的食材和做法</small></span>${icon('arrow')}</button><button data-action="manual"><span class="entry-symbol">✎</span><span><strong>自己写一道菜</strong><small>记下你的拿手配方</small></span>${icon('arrow')}</button><button data-action="generate-text"><span class="entry-symbol">✧</span><span><strong>说说你想做什么</strong><small>描述你想做的菜</small></span>${icon('arrow')}</button></div>`);break;
        case 'future':sheet(d.feature,`<p class="sheet-note">这个生成入口将在后续迭代接入。这轮先体验厨房、点菜、准备食材和记录一餐。</p>${button('先手写一道菜','manual','','button-secondary')}`);break;
        case 'import':if(window.STATIC_PREVIEW)sheet('手机流程预览',`<p class="sheet-note">这个入口先体验厨房、点菜和准备一餐。分享链接识别请在电脑页面使用；你也可以先手写一道菜，继续体验。</p>${button('自己写一道菜','manual','','button-secondary')}`);else importSheet();break;
        case 'manual':editRecipe();break;
        case 'resume-draft':await resumeRecipeDraft();break;
        case 'reconnect':await A.refresh();break;
        case 'edit-recipe':editRecipe(state.recipes.find(row=>row.id===d.id));break;
        case 'family':family();break;
        case 'join-family':if(!A.user){authSheet();break;}sheet('加入他们的小厨房',`<p class="sheet-note">加入后会显示对方家庭的厨房和菜谱。你当前家庭的数据会保留在服务端，不会合并或删除。</p>`+form(field('家庭邀请码','code','','text','required maxlength="20" placeholder="输入家人发来的邀请码"'),'account-join'));break;
        case 'settings':settings();break;
        case 'calendar-month':calendarMonth=new Date(calendarMonth.getFullYear(),calendarMonth.getMonth()+Number(d.delta),1);calendarDay='';render();break;
        case 'calendar-day':calendarDay=calendarDay===d.date?'':d.date;render();break;
        case 'calendar-clear':calendarDay='';render();break;
        case 'record':showRecord(state.records.find(row=>row.id===d.id));break;
        case 'photo':photoRecord=d.id;$('photo-file').click();break;
        case 'share-record':shareMenu(state.records.find(row=>row.id===d.id));break;
        case 'share-menu':shareMenu();break;
        case 'download-share':{const a=document.createElement('a');a.href=shareImage;a.download='一起吃饭-菜单.png';a.click();break;}
        case 'export':{const blob=new Blob([JSON.stringify(store.snapshot(state.recipes.filter(card=>!card.id.startsWith('demo-'))),null,2)],{type:'application/json'});const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='一起吃饭-食谱备份.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);break;}
      }
    } catch(error) {toast(error.message);}
  });
  document.addEventListener('submit',async event=>{
    const element=event.target.closest('[data-form]');if(!element) return;event.preventDefault();
    const values=Object.fromEntries(new FormData(element)),type=element.dataset.form;
    if(type.startsWith('account-')){await accountSubmit(element,values);return;}
    if(!A.ready || A.syncing){element.querySelector('.form-error').textContent='正在同步，请稍后再保存';return;}
    try {
      let pending;
      if(type==='generate') {
        const submit=element.querySelector('.button-primary'),version=sheetVersion;submit.disabled=true;
        try{const input={prompt:values.prompt || ''};if(element.dataset.kind==='image')input.image=await JobsClient.upload(values.image);if(element.dataset.kind==='ingredients')input.ingredients=values.ingredients;await beginJob(element.dataset.kind,input,version);}finally{submit.disabled=false;}
        return;
      }
      if(type==='parse') {element.querySelector('.button-primary').disabled=true;await parseRecipes(values);return;}
      if(type==='join') {toast('这是邀请流程预览，真实账号与入组下一轮接入。');return;}
      if(type==='prepare') {let op=mutate('meal.prepare',{needId:element.dataset.id,direction:element.dataset.type,quantity:values.quantity,unit:values.unit},()=>C.prepare(state,element.dataset.id,element.dataset.type,values.quantity,values.unit));if(op?.then)op=await op;close();return;}
      if(type==='add-stock') {const [space,zone]=values.location.split(':'),input={...values,space:space==='unplaced'?null:space,zone:Number(zone || 0)};pending=mutate('stock.add',input,()=>C.addStock(state,input));if(pending?.then)await pending;}
      if(type==='reduce-stock') {pending=mutate('stock.reduce',{stockId:element.dataset.id,quantity:values.quantity},()=>C.reduceStock(state,element.dataset.id,values.quantity));if(pending?.then)await pending;}
      if(type==='move-stock') {const [space,zone]=values.location.split(':'),input={stockId:element.dataset.id,space:space==='unplaced'?null:space,zone:Number(zone || 0)};pending=mutate('stock.move',input,()=>C.moveStock(state,input.stockId,input.space,input.zone));if(pending?.then)await pending;}
      if(type==='add-space') {const zones=C.layoutZones(values.layout).map((label,i)=>values[`zone-${i}`]?.trim() || label);pending=mutate('space.create',{name:values.name,type:values.type,layout:values.layout,zones},()=>{if(state.role!=='chef')throw Error('请切换到主厨来操作');const name=values.name.trim();if(!name)throw Error('请填写空间名字');state.spaces.push({id:C.uid(),name,type:values.type,layout:values.layout,zones});});if(pending?.then)await pending;transact(()=>{state.spaceIndex=state.spaces.length-1;},false);}
      if(type==='layout') {const zones=C.layoutZones(values.layout).map((label,i)=>values[`zone-${i}`]?.trim() || label);pending=mutate('space.update',{spaceId:element.dataset.id,name:values.name,layout:values.layout,zones},()=>C.updateSpace(state,element.dataset.id,values.name,values.layout,zones));if(pending?.then)await pending;}
      if(type==='recipe') {
        const original=state.recipes.find(row=>row.id===element.dataset.id);
        if(recipeDraft?.coverBusy)throw Error('图片正在处理，请稍等');
        const ingredients=[...element.querySelectorAll('.recipe-ingredient-row')].map(row=>{const name=row.querySelector('[data-ingredient-name]').value.trim(),q=row.querySelector('[name="ingredientQuantity"]').value.trim(),unit=row.querySelector('[name="ingredientUnit"]').value,iconId=row.querySelector('[data-ingredient-icon]').value;const quantity=q===''?null:Number(q);if(!name || quantity!==null&&(!Number.isFinite(quantity)||quantity<0))throw Error('请填写食材名字和有效用量，不确定时用量可留空');const old=original?.ingredients[Number(row.dataset.originalIndex)],same=old?.name===name&&old?.quantity===quantity&&displayUnit(old?.unit)===unit;return {...(same?old:{}),name,iconId,quantity:unit?quantity:null,unit,pending:quantity===null||!unit,evidence:same?old.evidence || '用户填写':'用户填写'};});
        if(!ingredients.length)throw Error('至少添加一种食材');
        const steps=[...element.querySelectorAll('[name="recipeStep"]')].map(input=>input.value.trim()).filter(Boolean);
        const card=store.normalize({...original,id:original?.id || C.uid(),name:values.name.trim(),servings:1,ingredients,coverImage:recipeDraft?.coverImage || null,steps,evidenceIds:original?.evidenceIds || [],source:original?.source || '',reviewMode:'用户手动记录'});
        if(!card.name || !card.steps.length)throw Error('请填写菜名和制作步骤');
        pending=mutate('recipe.upsert',{recipe:card,evidence:Object.fromEntries(store.resolve(card).map(row=>[row.id,row]))},()=>{const index=state.recipes.findIndex(row=>row.id===card.id);if(index<0)state.recipes.unshift(card);else state.recipes[index]=card;});if(pending?.then)await pending;if(!card.id.startsWith('demo-'))rememberReal(card);
        void window.LocalCache?.removeDraft(draftOwner());
      }
      close();
    } catch(error) {element.querySelector('.form-error').textContent=error.message;}
  });
  document.addEventListener('input',event=>{
    if(event.target.closest('[data-form="recipe"]'))void saveRecipeDraft();
    if(event.target.id==='stock-search'){search=event.target.value;region('stock-results',stockResults());}
    if(event.target.id==='recipe-search'){recipeSearch=event.target.value;region('recipe-results',recipeResults());}
  });
  document.addEventListener('change',async event=>{
    if(event.target.closest('[data-form="recipe"]') && event.target.type!=='file')void saveRecipeDraft();
    if(event.target.id==='account-avatar-file') {
      const file=event.target.files[0];if(!file)return;let url;const draft=profileDraft;draft.busy=true;
      try {
        if(!['image/png','image/jpeg','image/webp'].includes(file.type)||file.size>10000000)throw Error('请选择10MB以内的图片');
        url=URL.createObjectURL(file);const image=new Image();image.src=url;await image.decode();
        const canvas=document.createElement('canvas');canvas.width=canvas.height=256;const ctx=canvas.getContext('2d'),size=Math.min(image.width,image.height);
        ctx.fillStyle='#e8f0e3';ctx.fillRect(0,0,256,256);ctx.drawImage(image,(image.width-size)/2,(image.height-size)/2,size,size,0,0,256,256);draft.avatar=canvas.toDataURL('image/jpeg',.85);
        if(profileDraft===draft&&$('account-avatar-preview'))$('account-avatar-preview').innerHTML=avatar(draft);
      }catch(error){toast(error.message || '头像读取失败，请换一张图片');}finally{draft.busy=false;if(url)URL.revokeObjectURL(url);event.target.value='';}return;
    }
    if(event.target.matches('.select-control select'))syncSelect(event.target);
    if(event.target.id==='recipe-cover-file') {await uploadRecipeCover(event.target.files[0],event.target.closest('form'));event.target.value='';return;}
    if(event.target.matches('[data-layout-select]')) {const parent=event.target.closest('form'),names=parent._zoneNames || [];parent.querySelectorAll('[name^="zone-"]').forEach(input=>{names[Number(input.name.slice(5))]=input.value;});parent._zoneNames=names;$('zone-name-editor').innerHTML=zoneFields(event.target.value,names);}
    if(event.target.id==='random-count') {const count=Number(event.target.value);try{randomRows=C.sample(state.recipes,count,randomLocked);randomCount=count;randomSheet(true);}catch(error){event.target.value=randomCount;syncSelect(event.target);toast(error.message);}}
  });
  document.addEventListener('keydown',event=>{
    const options=document.querySelector('.select-options:not([hidden]),.ingredient-options:not([hidden])');if(!options)return;
    const custom=options.classList.contains('select-options'),toggle=options.parentElement.querySelector(custom?'.select-trigger':'[data-action="ingredient-toggle"]');
    if(event.key==='Escape') {event.preventDefault();options.hidden=true;toggle.setAttribute('aria-expanded','false');toggle.focus();}
    if(event.key==='Tab') {options.hidden=true;toggle.setAttribute('aria-expanded','false');}
    if(['ArrowDown','ArrowUp','Home','End'].includes(event.key)) {event.preventDefault();const choices=[...options.querySelectorAll('[role="option"]')],index=choices.indexOf(document.activeElement),next=event.key==='Home'?0:event.key==='End'?choices.length-1:(index+(event.key==='ArrowDown'?1:-1)+choices.length)%choices.length;choices[next].focus();}
  });
  $('photo-file').addEventListener('change',async event=>{
    const file=event.target.files[0],recordId=photoRecord;if(!file)return;
    let url;
    try {
      if(!file.type.startsWith('image/'))throw Error('请选择图片');
      url=URL.createObjectURL(file);const image=new Image();image.src=url;await image.decode();
      const scale=Math.min(1,900/Math.max(image.width,image.height)),canvas=document.createElement('canvas');canvas.width=Math.round(image.width*scale);canvas.height=Math.round(image.height*scale);canvas.getContext('2d').drawImage(image,0,0,canvas.width,canvas.height);
      const photo=canvas.toDataURL('image/jpeg',.72);await mutate('record.photo',{recordId,photo},()=>{const record=state.records.find(row=>row.id===recordId);if(!record)throw Error('本餐记录不存在');record.photo=photo;});showRecord(state.records.find(row=>row.id===recordId));
    } catch(error){toast(error.message || '这张图片暂时无法读取，请换一张');}
    finally{if(url)URL.revokeObjectURL(url);event.target.value='';}
  });
  document.addEventListener('pointerdown',event=>{
    if(event.target.closest('button,input,select,textarea,a') || state.role!=='chef' || $('sheet').open)return;
    const row=event.target.closest('[data-swipe]'),space=event.target.closest('[data-space-swipe]');
    if(row || space)swipe={x:event.clientX,y:event.clientY,element:row || space,need:row?.dataset.need,pointerId:event.pointerId};
  });
  document.addEventListener('pointermove',event=>{
    if(!swipe || event.pointerId!==swipe.pointerId)return;
    const dx=event.clientX-swipe.x,dy=event.clientY-swipe.y;
    if(Math.abs(dy)>30&&Math.abs(dy)>Math.abs(dx)){swipe.element.style.transform='';swipe=null;return;}
    if(swipe.need&&Math.abs(dx)>12){swipe.element.style.transition='none';swipe.element.style.transform=`translateX(${Math.max(-95,Math.min(95,dx))}px)`;}
  });
  document.addEventListener('pointerup',event=>{
    if(!swipe || event.pointerId!==swipe.pointerId)return;
    const item=swipe;swipe=null;item.element.style.transform='';item.element.style.transition='';
    const dx=event.clientX-item.x,dy=event.clientY-item.y;
    if(Math.abs(dx)<55 || Math.abs(dy)>35)return;
    lastSwipe=Date.now();try{if(item.need)openPrepare(item.need,dx<0?'left':'right');else transact(()=>{state.spaceIndex=(state.spaceIndex+(dx<0?1:-1)+state.spaces.length)%state.spaces.length;},false);}catch(error){toast(error.message);}
  });
  document.addEventListener('pointercancel',()=>{if(swipe){swipe.element.style.transform='';swipe.element.style.transition='';}swipe=null;});
  window.addEventListener('storage',event=>{if(A.user || event.key!==KEY || !event.newValue)return;try{const saved=JSON.parse(event.newValue);store=RecipeData.createStore(saved.recipeData);state={...saved.state,recipes:store.recipes};render();}catch{toast('本机页面同步失败，请刷新后核对');}});
  void A.start({
    apply(data) {
      let view={role:state.role,page:state.page,spaceIndex:state.spaceIndex};
      if(viewAccountId!==A.user.id){latestJob=null;localJob=null;try{const cached=JSON.parse(localStorage.getItem('together-account-cache-'+A.user.id));if(cached?.state)view={role:cached.state.role==='foodie'?'foodie':'chef',page:['kitchen','recipes','meal','mine'].includes(cached.state.page)?cached.state.page:'kitchen',spaceIndex:Number.isInteger(cached.state.spaceIndex)?cached.state.spaceIndex:0};}catch(_){}viewAccountId=A.user.id;}
      store=RecipeData.createStore(data.recipeData);
      state={...data.state,...view,recipes:store.recipes.map(card=>store.normalize(oneRecipe(card)))};
      state.stocks=state.stocks.map(stock=>({...stock,iconId:fixedIcon(stock)}));
      persist();
    },
    guest() {
      close();viewAccountId=null;search='';recipeSearch='';randomRows=[];randomLocked=[];parseResume=null;profileDraft=null;latestJob=null;localJob=null;
      let saved;try{saved=JSON.parse(localStorage.getItem(KEY) || 'null');}catch(_){}
      const initial=saved?.state || C.seed();store=RecipeData.createStore(saved?.recipeData || initial.recipes);
      state={...initial,recipes:store.recipes,page:'mine'};
    },render,notify:toast
  });
  render();if(bootError)toast(bootError);
  if(navigator.serviceWorker && !window.Capacitor?.isNativePlatform?.())navigator.serviceWorker.register('/offline-worker.js').catch(()=>{});
})();
