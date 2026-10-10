/* Cookie authentication; account and household identity never comes from localStorage. */
(() => {
  const client={user:null,household:null,members:[],revision:0,ready:true,available:false,syncing:false};
  let hooks,confirmed=null,queue=[],refreshing=false;
  async function request(path,payload) {
    const response=await fetch(path,{method:payload?'POST':'GET',credentials:'same-origin',headers:payload?{'Content-Type':'application/json'}:{},...(payload?{body:JSON.stringify(payload)}:{})});
    const data=await response.json();
    if(!response.ok){const error=Error(data.error || '请求失败，请重试');error.status=response.status;throw error;}
    return data;
  }
  function adopt(data,apply=true) {
    client.user=data.user;client.household=data.household || null;client.members=data.members || [];client.revision=data.revision || 0;
    if(data.snapshot)confirmed=KitchenCore.clone(data.snapshot);
    if(apply && data.snapshot)hooks.apply(data.snapshot);
    hooks.render();
  }
  client.start=async config=>{
    hooks=config;
    if(typeof fetch!=='function' || window.STATIC_PREVIEW)return;
    client.ready=false;
    try {const data=await request('/api/account/session');client.available=true;adopt(data);}
    catch(error){client.available=false;}
    finally{client.ready=true;hooks.render();}
    setInterval(()=>client.refresh().catch(()=>{}),4000);
    document.addEventListener('visibilitychange',()=>{if(!document.hidden)client.refresh().catch(()=>{});});
  };
  client.authenticate=async (type,payload)=>{if(client.user)throw Error('请先退出当前账号');adopt(await request('/api/account/'+type,payload));};
  client.profile=async payload=>{const data=await request('/api/account/profile',payload);adopt(data,client.revision!==data.revision);};
  client.join=async code=>{if(client.syncing)throw Error('正在保存厨房，请稍后再加入');adopt(await request('/api/household/join',{code}));};
  client.logout=async()=>{
    if(client.syncing)throw Error('正在保存厨房，请稍后再退出');
    await request('/api/account/logout',{});
    const id=client.user?.id;if(id)localStorage.removeItem('together-account-cache-'+id);
    confirmed=null;adopt({user:null},false);hooks.guest();hooks.render();
  };
  client.refresh=async()=>{
    if(!client.user || client.syncing || document.hidden || refreshing)return;
    const identity=client.user.id,household=client.household.id,revision=client.revision;refreshing=true;
    let data;try{data=await request('/api/account/session?revision='+revision+'&household='+encodeURIComponent(household));}finally{refreshing=false;}
    if(client.user?.id!==identity || client.household?.id!==household || client.revision!==revision || client.syncing)return;
    if(!data.user){await client.expired();return;}
    const changed=client.household?.id!==data.household.id || client.revision!==data.revision;
    if(!changed && JSON.stringify([client.user,client.members])===JSON.stringify([data.user,data.members]))return;
    // Do not replace an open form; its next save still checks the server revision.
    if(changed && document.getElementById('sheet').open)return;
    adopt(data,changed);
  };
  client.expired=async()=>{const id=client.user?.id;if(id)localStorage.removeItem('together-account-cache-'+id);confirmed=null;adopt({user:null},false);hooks.guest();hooks.render();hooks.notify('登录已过期，请重新登录');};
  client.commit=snapshot=>{
    queue.push(KitchenCore.clone(snapshot));
    if(!client.syncing)void drain();
  };
  async function drain() {
    client.syncing=true;
    try {
      while(queue.length) {
        const snapshot=queue[0];const data=await request('/api/household/save',{revision:client.revision,snapshot});
        client.revision=data.revision;confirmed=snapshot;queue.shift();
      }
    } catch(error) {
      // Retain unsaved input as a recoverable local backup, never overwrite newer family data.
      try {localStorage.setItem('together-unsaved-'+client.user.id,JSON.stringify(queue.at(-1)));}catch(_){}
      queue=[];
      if(confirmed)hooks.apply(confirmed);
      if(error.status===401)await client.expired();
      else {
        if(error.status===409){try{const data=await request('/api/account/session');if(data.user)adopt(data);else await client.expired();}catch(_) {}}
        hooks.notify(error.status===409?error.message:'这次修改未保存，请检查连接后重试');
      }
    } finally {client.syncing=false;hooks.render();}
  }
  client.request=request;
  window.AccountClient=client;
})();
