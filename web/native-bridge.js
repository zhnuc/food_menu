/* Bundled app talks to an explicit server; the public UI also runs offline. */
(() => {
  const native=()=>Boolean(window.Capacitor?.isNativePlatform?.());
  const root=()=>localStorage.getItem('together-server-url') || window.APP_API_URL || '';
  const original=window.fetch.bind(window);
  window.NativeBridge={native,root,url:path=>root()+path,setRoot:value=>{
    const url=new URL(value);
    if(!['https:',...(window.APP_ALLOW_HTTP?['http:']:[])].includes(url.protocol) || url.username || url.password || url.pathname!=='/' || url.search || url.hash)throw Error('请填写有效的 HTTPS 服务器根地址');
    localStorage.setItem('together-server-url',url.origin);
  }};
  window.fetch=(input,options)=>{
    if(native() && typeof input==='string' && (input.startsWith('/api/') || input.startsWith('/media/')))input=root()+input;
    return original(input,options);
  };
})();
