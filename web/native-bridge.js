/* Bundled app talks to an explicit server; the public UI also runs offline. */
(() => {
  const native=()=>Boolean(window.Capacitor?.isNativePlatform?.());
  const root=()=>window.APP_API_URL || '';
  const original=window.fetch.bind(window);
  window.NativeBridge={native,root,url:path=>root()+path};
  window.fetch=(input,options)=>{
    if(native() && typeof input==='string' && (input.startsWith('/api/') || input.startsWith('/media/')))input=root()+input;
    return original(input,options);
  };
})();
