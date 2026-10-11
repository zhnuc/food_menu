/* Static shell only. API, accounts and household photos never enter this cache. */
const CACHE='together-shell-78d5374abb64ce1b';
self.addEventListener('install',event=>event.waitUntil((async()=>{
  const manifest=await (await fetch('/offline-assets.json',{cache:'no-store'})).json();
  const cache=await caches.open(CACHE);
  await cache.addAll(manifest.files);await self.skipWaiting();
})()));
self.addEventListener('activate',event=>event.waitUntil((async()=>{
  for(const key of await caches.keys())if(key.startsWith('together-shell-')&&key!==CACHE)await caches.delete(key);
  await self.clients.claim();
})()));
self.addEventListener('fetch',event=>{
  const url=new URL(event.request.url);
  if(event.request.method!=='GET'||url.origin!==self.location.origin||url.pathname.startsWith('/api/')||url.pathname.startsWith('/media/'))return;
  event.respondWith((async()=>{
    try{return await fetch(event.request);}catch(error){
      const match=await caches.match(event.request,{ignoreSearch:true});
      if(match)return match;
      if(event.request.mode==='navigate')return (await caches.match('/index.html'))||Response.error();
      throw error;
    }
  })());
});
