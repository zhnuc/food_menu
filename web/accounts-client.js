/* Cookie authentication; account and household identity never comes from localStorage. */
(() => {
  const client={user:null,household:null,members:[],revision:0,ready:true,available:false,syncing:false,pending:false,offline:false};
  let hooks,confirmed=null,refreshing=false;
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
    if(data.user && confirmed && !client.offline)window.LocalCache?.saveAccount({...data,snapshot:confirmed}).then(()=>window.PrivateAssets?.prefetch({...data,snapshot:confirmed})).catch(()=>hooks.notify('本地留档失败，云端记录仍然保留'));
    hooks.render();
  }
  client.start=async config=>{
    hooks=config;
    if(typeof fetch!=='function' || window.STATIC_PREVIEW)return;
    client.ready=false;
    try {const data=await request('/api/account/session');client.available=true;adopt(data);}
    catch(error){client.available=false;client.offline=true;try{const cached=await window.LocalCache?.restoreAccount();if(cached?.user && cached.snapshot)adopt(cached);}catch(_) {}}
    finally{client.ready=true;hooks.render();}
    if(client.user && !client.offline){try{await client.retryPending();}catch(error){hooks.notify(error.message);}}
    setInterval(()=>client.refresh().catch(()=>{}),4000);
    document.addEventListener('visibilitychange',()=>{if(!document.hidden)client.refresh().catch(()=>{});});
    window.addEventListener?.('online',()=>client.refresh().catch(()=>{}));
  };
  client.authenticate=async (type,payload)=>{if(client.user)throw Error('请先退出当前账号');const data=await request('/api/account/'+type,payload);client.offline=false;client.available=true;adopt(data);try{await client.retryPending();}catch(error){hooks.notify(error.message);}};
  client.profile=async payload=>{const data=await request('/api/account/profile',payload);adopt(data,client.revision!==data.revision);};
  client.join=async code=>{if(client.syncing || client.pending)throw Error('请先确认待同步的操作再加入家庭');adopt(await request('/api/household/join',{code}));};
  client.logout=async()=>{
    if(client.syncing)throw Error('正在保存厨房，请稍后再退出');
    await request('/api/account/logout',{});
    const id=client.user?.id;if(id){localStorage.removeItem('together-account-cache-'+id);await window.LocalCache?.forgetAccount(id);}
    confirmed=null;client.pending=false;adopt({user:null},false);hooks.guest();hooks.render();
  };
  client.disconnectLocal=async()=>{
    if(!window.NativeBridge?.native() || !client.offline)throw Error('请联网退出账号');
    if(client.syncing)throw Error('正在保存厨房，请稍后再退出');
    // Explicit recovery when the old server cannot be reached. Its session is
    // not revoked; clear device cookies before allowing another connection.
    const cookies=window.Capacitor?.Plugins?.CapacitorCookies;
    if(!cookies?.clearAllCookies)throw Error('无法清除本机登录，请重启 App 后重试');
    await cookies.clearAllCookies();
    const id=client.user?.id;if(id){localStorage.removeItem('together-account-cache-'+id);await window.LocalCache?.forgetAccount(id);}
    confirmed=null;client.pending=false;adopt({user:null},false);hooks.guest();hooks.render();
  };
  client.refresh=async()=>{
    if(!client.user || client.syncing || document.hidden || refreshing)return;
    const identity=client.user.id,household=client.household.id,revision=client.revision;refreshing=true;
    let data;try{data=await request('/api/account/session?revision='+revision+'&household='+encodeURIComponent(household));}catch(error){client.offline=true;hooks.render();throw error;}finally{refreshing=false;}
    if(client.user?.id!==identity || client.household?.id!==household || client.revision!==revision || client.syncing)return;
    if(!data.user){await client.expired();return;}
    const wasOffline=client.offline;client.offline=false;client.available=true;
    const changed=client.household?.id!==data.household.id || client.revision!==data.revision;
    if(!changed && JSON.stringify([client.user,client.members])===JSON.stringify([data.user,data.members])){if(wasOffline){hooks.render();window.PrivateAssets?.prefetch({...data,snapshot:confirmed});}return;}
    // Do not replace an open form; its next save still checks the server revision.
    if(changed && document.getElementById('sheet').open)return;
    adopt(data,changed);
  };
  client.expired=async()=>{const id=client.user?.id;if(id){localStorage.removeItem('together-account-cache-'+id);await window.LocalCache?.forgetAccount(id);}confirmed=null;client.pending=false;adopt({user:null},false);hooks.guest();hooks.render();hooks.notify('登录已过期，请重新登录');};
  client.command=async (kind,payload,context)=>{
    if(!client.user)throw Error('请先登录账号');
    if(client.offline)throw Error('当前离线，可以查看留档；家庭修改需要联网确认');
    if(client.syncing)throw Error('正在保存到家庭，请稍等');
    if(client.pending)throw Error('上次操作尚未确认，请先重试同步');
    const command={id:KitchenCore.uid(),revision:client.revision,kind,payload:KitchenCore.clone(payload),...context};
    return sendCommand(command);
  };
  client.retryPending=async()=>{
    if(!client.user || client.syncing || client.offline)return;
    const raw=localStorage.getItem('together-pending-'+client.user.id);
    if(!raw){client.pending=false;return;}
    const saved=JSON.parse(raw);
    if(saved.household!==client.household.id){client.pending=false;return;}
    client.pending=true;
    const {household,...command}=saved;
    return sendCommand(command);
  };
  async function sendCommand(command) {
    const identity=client.user.id,household=client.household.id;
    // Save before sending so closing the page cannot lose the id of an operation
    // that may have committed. Storage failure stops the write altogether.
    localStorage.setItem('together-pending-'+identity,JSON.stringify({...command,household}));
    client.pending=true;
    client.syncing=true;
    hooks.render();
    try {
      let data;
      try {data=await request('/api/household/commands',command);}
      catch(error) {
        // A lost response may mean the server committed. Retry the same receipt
        // id, never create a second inventory operation for a transport failure.
        if(error.status)throw error;
        data=await request('/api/household/commands',command);
      }
      if(client.user?.id!==identity || client.household?.id!==household)throw Error('账号或家庭已变化，请重新打开页面');
      localStorage.removeItem('together-pending-'+identity);client.pending=false;
      adopt(data);return data.result;
    } catch(error) {
      if(client.user?.id!==identity || client.household?.id!==household)throw error;
      // Keep a receipt, not a fabricated new snapshot. This is a recovery record,
      // not an offline write queue: don't replay it under a new meal or account.
      if(error.status && error.status<500){localStorage.removeItem('together-pending-'+identity);client.pending=false;}
      if(error.status===401)await client.expired();
      else if(error.status===409){try{const data=await request('/api/account/session');if(data.user)adopt(data);else await client.expired();}catch(_) {}}
      throw error;
    } finally {client.syncing=false;hooks.render();}
  }
  client.request=request;
  window.AccountClient=client;
})();
