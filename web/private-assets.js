/* Session images are cached per account; never in the public service worker. */
(() => {
  const valid=url=>/^\/api\/files\/[a-f0-9]{32}$/.test(url || '') || /^\/media\/[a-f0-9]{24}\/(?:frame-\d+\.jpg|image-\d+\.(?:jpg|png|webp))$/.test(url || '');
  let owner=null;const urls=new Map(),pending=new Map();
  function identity() {
    const current=window.AccountClient?.user?.id || null;
    if(owner!==current){for(const url of urls.values())URL.revokeObjectURL(url);urls.clear();pending.clear();owner=current;}
    return current;
  }
  async function load(asset) {
    const account=identity();if(!account || !valid(asset))return '';
    if(urls.has(asset))return urls.get(asset);if(pending.has(asset))return pending.get(asset);
    const task=(async()=>{
      let blob=await window.LocalCache?.readAsset(account,asset);
      if(!blob && !window.AccountClient.offline) {
        const response=await fetch(asset,{credentials:'same-origin'});
        if(!response.ok)throw Error('图片暂不可用');blob=await response.blob();
        if(blob.size>8000000 || !blob.type.startsWith('image/'))throw Error('图片格式不正确');
        if(identity()!==account)return '';
        await window.LocalCache?.saveAsset(account,asset,blob);
      }
      if(!blob || identity()!==account)return '';
      const url=URL.createObjectURL(blob);urls.set(asset,url);return url;
    })().finally(()=>pending.delete(asset));pending.set(asset,task);return task;
  }
  let prefetching=false,prefetchTarget=null;
  async function prefetch(data) {
    prefetchTarget=data;if(prefetching)return;prefetching=true;
    try {
      while(prefetchTarget) {
        const target=prefetchTarget;prefetchTarget=null;
        const account=identity(),assets=new Set();
        if(!account || window.AccountClient.offline)continue;
        const collect=value=>{if(typeof value==='string' && valid(value))assets.add(value);else if(value && typeof value==='object')Object.values(value).forEach(collect);};
        collect(target);
        const queue=[...assets];
        await Promise.all([0,1].map(async()=>{
          while(queue.length && identity()===account && !window.AccountClient.offline) {
            const asset=queue.shift();
            try {
              if(await window.LocalCache?.readAsset(account,asset))continue;
              const response=await fetch(asset,{credentials:'same-origin'});
              if(!response.ok)continue;const blob=await response.blob();
              if(identity()===account && blob.size<=8000000 && blob.type.startsWith('image/'))await window.LocalCache?.saveAsset(account,asset,blob);
            } catch(_) { /* A later confirmed snapshot retries unfinished downloads. */ }
          }
        }));
      }
    } finally {prefetching=false;}
  }
  function hydrate() {
    if(!window.document)return;
    identity();
    for(const image of document.querySelectorAll('img[data-private-asset]')) {
      if(image.dataset.assetLoading)continue;
      image.dataset.assetLoading='1';const asset=image.dataset.privateAsset;
      load(asset).then(url=>{if(url && image.dataset.privateAsset===asset)image.src=url;else delete image.dataset.assetLoading;}).catch(()=>{delete image.dataset.assetLoading;});
    }
  }
  window.PrivateAssets={valid,load,prefetch,attributes:url=>valid(url)?'src="/assets/dishes/v1/256/default-dish.png" data-private-asset="'+url+'"':'src="'+String(url).replace(/&/g,'&amp;').replace(/"/g,'&quot;')+'"'};
  new MutationObserver(hydrate).observe(document.documentElement,{childList:true,subtree:true});
  window.addEventListener('online',hydrate);
})();
