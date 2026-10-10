"""DyNote page collection subset; modified 2026-10-10 for food_menu.
Original MIT license and revision are retained alongside this file.
Only page collection and media lookup are retained; the caller supplies eval_js.
"""
from __future__ import annotations
from typing import Any

class DouyinTextError(RuntimeError):
    pass

def eval_js(target: str, js: str, timeout: int = 30) -> Any:
    raise DouyinTextError("Browser evaluation transport has not been attached")

def collect_page_info(target: str) -> dict[str, Any]:
    js = r"""
(() => {
  const text = (sel) => {
    const el = document.querySelector(sel);
    return el ? (el.content || el.textContent || '').trim() : '';
  };
  const url = location.href;
  const title = document.title || '';
  const metaDescription = text('meta[name="description"]') || text('meta[property="og:description"]');
  const ogTitle = text('meta[property="og:title"]');
  const videos = Array.from(document.querySelectorAll('video')).map(v => ({
    src: v.currentSrc || v.src || '',
    duration: Number.isFinite(v.duration) ? v.duration : null,
    poster: v.poster || '',
    readyState: v.readyState
  })).filter(v => v.src);
  const tracks = Array.from(document.querySelectorAll('track')).map(t => ({
    kind: t.kind || '',
    label: t.label || '',
    srclang: t.srclang || '',
    src: t.src || ''
  })).filter(t => t.src);
  const resources = performance.getEntriesByType('resource')
    .map(e => e.name)
    .filter(u => /\.(mp4|m4a|mp3|webm)(\?|$)/i.test(u) || /video|playwm|play_addr/i.test(u))
    .slice(-30);

  const seen = new WeakSet();
  const details = [];
  function scan(obj, depth) {
    if (!obj || typeof obj !== 'object' || depth > 6 || seen.has(obj) || details.length > 8) return;
    seen.add(obj);
    try {
      if ((obj.aweme_id || obj.awemeId || obj.item_id) && (obj.desc || obj.video || obj.author)) {
        details.push(obj);
      }
      for (const key of Object.keys(obj).slice(0, 80)) scan(obj[key], depth + 1);
    } catch (e) {}
  }
  for (const key of Object.keys(window)) {
    if (/INITIAL|RENDER|DATA|STATE|aweme/i.test(key)) {
      try { scan(window[key], 0); } catch (e) {}
    }
  }
  const scripts = Array.from(document.scripts).map(s => s.textContent || '').join('\n');
  const idMatch = url.match(/\/(?:note|video)\/(\d+)/) || scripts.match(/"aweme_id"\s*:\s*"(\d+)"/) || scripts.match(/"awemeId"\s*:\s*"(\d+)"/);
  return {
    url, title, ogTitle, metaDescription, videos, tracks, resources,
    aweme_id: idMatch ? idMatch[1] : '',
    detail: details[0] || null
  };
})()
"""
    value = eval_js(target, js, timeout=20)
    if not isinstance(value, dict):
        raise DouyinTextError(f"Unexpected page info result: {type(value).__name__}")
    return value

def find_media_url(info: dict[str, Any]) -> str:
    candidates = []
    for video in info.get("videos") or []:
        if isinstance(video, dict) and video.get("src"):
            candidates.append(str(video["src"]))
    candidates.extend(str(url) for url in info.get("resources") or [])
    for url in candidates:
        if url.startswith("http") and not url.startswith("blob:"):
            return url
    raise DouyinTextError("Could not find a downloadable media URL on the Douyin page.")
