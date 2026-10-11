/* Durable jobs: resume after app closure or server restart. */
(() => {
  async function request(path,body) {
    const response=await fetch(path,{credentials:'same-origin',...(body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{})});
    const data=await response.json();if(!response.ok){const error=Error(data.error || '任务请求失败');error.status=response.status;throw error;}return data;
  }
  const jobs={
    list:()=>request('/api/jobs'),get:id=>request('/api/jobs/'+encodeURIComponent(id)),
    action:(id,action)=>request('/api/jobs/'+encodeURIComponent(id)+'/'+action,{}),
    async create(kind,input) {
      const body={requestId:KitchenCore.uid(),kind,input};
      try{return await request('/api/jobs',body);}catch(error){if(!error.status)return request('/api/jobs',body);throw error;}
    },
    async follow(id,onEvent) {
      let after=0;const started=Date.now();
      while(Date.now()-started<3600000) {
        const data=await request('/api/jobs/'+encodeURIComponent(id)+'?after='+after);
        for(const event of data.events){await onEvent(event);after=Math.max(after,event.sequence);}
        if(data.status==='succeeded') {
          await onEvent({type:'source',evidence:data.result.evidence || [],media:data.result.media || {}});
          await onEvent({type:'recipes',recipes:data.result.recipes || []});
          await onEvent({type:'done',recipeCount:data.result.recipes?.length || 0,warnings:data.result.warnings || [],timings:data.result.timings || {}});return;
        }
        if(['failed','cancelled'].includes(data.status))throw Error(data.error || '任务已取消');
        await new Promise(resolve=>setTimeout(resolve,2000));
      }
      throw Error('任务仍在服务器处理，可在设置中的“菜谱生成任务”查看');
    },
    async upload(file) {
      if(!file || file.size>8000000)throw Error('请选择8MB以内的菜谱图片');
      const response=await fetch('/api/files?purpose=recipe-input',{method:'POST',credentials:'same-origin',headers:{'Content-Type':file.type || 'application/octet-stream'},body:file});
      const data=await response.json();if(!response.ok)throw Error(data.error || '图片上传失败');return data.url;
    }
  };
  if(typeof module!=='undefined')module.exports=jobs;else window.JobsClient=jobs;
})();
