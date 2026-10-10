/* Fetch events as soon as a validated group arrives; retain JSON compatibility. */
(() => {
  async function readEvents(response, onEvent) {
    if (!response.ok) {
      const data = await response.json();
      throw Error(data.error || '服务请求失败');
    }
    if (!(response.headers.get('content-type') || '').includes('application/x-ndjson')) {
      const data = await response.json();
      onEvent({type: 'source', evidence: data.evidence || [], media: data.media || {}});
      onEvent({type: 'recipes', recipes: data.recipes || []});
      onEvent({type: 'done', recipeCount: data.recipes?.length || 0, warnings: data.warnings, timings: data.timings});
      return;
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '', done = false;
    function dispatch(line) {
      if (!line.trim()) return;
      const event = JSON.parse(line);
      if (event.type === 'error') throw Error(event.error);
      if (event.type === 'done') done = true;
      onEvent(event);
    }
    try {
      while (true) {
        const chunk = await reader.read();
        buffer += decoder.decode(chunk.value || new Uint8Array(), {stream: !chunk.done});
        let end;
        while ((end = buffer.indexOf('\n')) >= 0) {
          dispatch(buffer.slice(0, end));
          buffer = buffer.slice(end + 1);
        }
        if (chunk.done) break;
      }
      dispatch(buffer);
      if (!done) throw Error('连接中断，已生成的卡片已保留，可重试补齐。');
    } finally {
      reader.releaseLock();
    }
  }
  async function generate(body, onEvent) {
    return readEvents(await fetch('/api/parse', {method: 'POST', headers: {
      'Content-Type': 'application/json', 'Accept': 'application/x-ndjson'}, body: JSON.stringify(body)}), onEvent);
  }
  const api = {readEvents, generate};
  if (typeof module !== 'undefined') module.exports = api;
  else globalThis.RecipeStream = api;
})();
