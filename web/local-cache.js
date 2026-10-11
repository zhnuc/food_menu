/* Account-scoped IndexedDB copies and drafts. Never a credential store. */
(() => {
  let database,tail=Promise.resolve();const forgotten=new Set();
  const LAST='together-last-cached-account';
  function open() {
    if(!window.indexedDB)return Promise.resolve(null);
    if(!database)database=new Promise((resolve,reject)=>{
      const request=window.indexedDB.open('together-kitchen-local',2);
      request.onupgradeneeded=()=>{for(const name of ['accounts','drafts','assets'])if(!request.result.objectStoreNames.contains(name))request.result.createObjectStore(name);};
      request.onsuccess=()=>resolve(request.result);request.onerror=()=>reject(request.error);
    });
    return database;
  }
  function operation(store,key,value,remove=false) {
    const task=tail.catch(()=>{}).then(async()=>{
      const db=await open();if(!db)return null;
      return new Promise((resolve,reject)=>{
        const tx=db.transaction(store,value===undefined&&!remove?'readonly':'readwrite'),object=tx.objectStore(store);
        const request=remove?object.delete(key):value===undefined?object.get(key):object.put(value,key);
        tx.oncomplete=()=>resolve(request.result ?? null);tx.onerror=()=>reject(tx.error);tx.onabort=()=>reject(tx.error || Error('本地存储失败'));
      });
    });
    tail=task;return task;
  }
  const cache={
    async saveAccount(data) {
      if(!data.user || !data.snapshot)return;
      forgotten.delete(data.user.id);
      await operation('accounts',data.user.id,{...data,cachedAt:Date.now()});
      if(window.indexedDB)localStorage.setItem(LAST,data.user.id);
    },
    async restoreAccount() {
      await tail.catch(()=>{});
      const id=localStorage.getItem(LAST);return id?operation('accounts',id):null;
    },
    async forgetAccount(id) {
      forgotten.add(id);
      await operation('accounts',id,undefined,true);
      await operation('drafts',id,undefined,true);
      const task=tail.catch(()=>{}).then(async()=>{
        const db=await open();if(!db)return;
        await new Promise((resolve,reject)=>{
          const tx=db.transaction('assets','readwrite'),cursor=tx.objectStore('assets').openCursor();
          cursor.onsuccess=()=>{const row=cursor.result;if(row){if(String(row.key).startsWith(id+'|'))row.delete();row.continue();}};
          tx.oncomplete=resolve;tx.onerror=()=>reject(tx.error);
        });
      });tail=task;await task;
      if(localStorage.getItem(LAST)===id)localStorage.removeItem(LAST);
    },
    saveDraft(owner,draft) {return operation('drafts',owner,{...draft,savedAt:Date.now()});},
    readDraft(owner) {return operation('drafts',owner);},
    removeDraft(owner) {return operation('drafts',owner,undefined,true);},
    readAsset(owner,url) {return operation('assets',owner+'|'+url);},
    saveAsset(owner,url,blob) {return forgotten.has(owner)?Promise.resolve(null):operation('assets',owner+'|'+url,blob);}
  };
  window.LocalCache=cache;
})();
