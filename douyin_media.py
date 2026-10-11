"""Douyin photo/video acquisition, with DyNote's browser collection adapter.

Public mobile page data is tried first. The fallback renders the public page
in an isolated, headless Chrome context (never the user's browser profile).
Media URLs are transport details; they are never written into source metadata.
"""
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse
from urllib.request import Request,ProxyHandler,build_opener

_UA='Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1'


def _walk(value):
    if isinstance(value,dict):
        if (value.get('aweme_id') or value.get('awemeId') or value.get('item_id')) and (value.get('video') or value.get('images') or value.get('image_post_info')):
            yield value
        for child in value.values():yield from _walk(child)
    elif isinstance(value,list):
        for child in value:yield from _walk(child)


def _share(url):
    from video_media import SafeRedirect
    req=Request(url,headers={'User-Agent':_UA})
    opener=build_opener(ProxyHandler({}),SafeRedirect(('douyin.com','iesdouyin.com')))
    with opener.open(req,timeout=25) as response:
        target=response.url
        html=response.read(2_000_001).decode('utf-8','replace')
    if len(html)>2_000_000:raise ValueError('抖音分享页超过读取上限')
    detail=None
    match=re.search(r'window\._ROUTER_DATA\s*=\s*',html)
    if match:
        try:detail=next(_walk(json.JSONDecoder().raw_decode(html[match.end():])[0]),None)
        except (ValueError,TypeError):pass
    match=re.search(r'/(?:share/)?(?:video|note)/(\d{10,24})',target)
    if not match:match=re.search(r'(?:modal_id|aweme_id|item_id)=(\d{10,24})',target)
    if not match:raise ValueError('抖音短链已打开，但未识别到作品编号')
    return target,match.group(1),detail


def _browser_info(url,module):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise ValueError('抖音分享页需浏览器渲染；请安装项目的 Playwright 依赖') from exc
    with sync_playwright() as runtime:
        # A fresh context is intentionally independent of logged-in Chrome.
        # Login/verification challenges are reported, never automatically solved.
        browser=runtime.chromium.launch(channel=os.getenv('DOUYIN_BROWSER_CHANNEL','chrome') or None,
                                       headless=True,args=['--no-proxy-server'])
        try:
            context=browser.new_context(user_agent=_UA,viewport={'width':390,'height':844},is_mobile=True,has_touch=True)
            page=context.new_page()
            for attempt in range(2):
                try:
                    page.goto(url,wait_until='domcontentloaded',timeout=35000)
                    break
                except Exception:
                    if attempt:raise
            module.eval_js=lambda target,js,timeout=30:page.evaluate(js)
            info={}
            for _ in range(5):
                page.wait_for_timeout(1800)
                info=module.collect_page_info('isolated-public-page')
                # The mobile router's item data may appear after hydration.
                if not info.get('detail'):
                    router=page.evaluate('() => window._ROUTER_DATA || null')
                    info['detail']=next(_walk(router),None)
                if info.get('detail') or info.get('videos'):break
            # Photo posts can expose picture elements without an initial state.
            info['visibleImages']=page.evaluate('''() => Array.from(document.images)
                .filter(i => i.naturalWidth >= 300 && i.naturalHeight >= 200)
                .map(i => i.currentSrc || i.src).filter(Boolean)''')
            info['pageText']=page.locator('body').inner_text(timeout=5000)[:3000]
            return info
        finally:browser.close()


def _urls(record):
    if not isinstance(record,dict):return []
    for key in ['url_list','urlList','urls']:
        if isinstance(record.get(key),list):return [u for u in record[key] if isinstance(u,str)]
    for key in ['display_image','displayImage','origin_image','originImage','download_url','downloadUrl']:
        if isinstance(record.get(key),dict):
            values=_urls(record[key])
            if values:return values
    return []


def _pictures(detail,info):
    pictures=detail.get('images') or (detail.get('image_post_info') or {}).get('images') or []
    urls=[]
    for image in pictures:
        values=_urls(image)
        if values:urls.append(values[0])
    # Generic DOM images include recommendations and avatars. Only the
    # requested work's detail may supply recipe images.
    return list(dict.fromkeys(urls))


def _image(url,directory,index,download):
    path=download(url,directory/f'image-{index:02}.jpg',{'User-Agent':_UA},15_000_000)
    start=path.read_bytes()[:16]
    if start.startswith(b'\xff\xd8'):suffix='.jpg'
    elif start.startswith(b'\x89PNG'):suffix='.png'
    elif start[:4]==b'RIFF' and start[8:12]==b'WEBP':suffix='.webp'
    else:
        from video_media import _ffmpeg
        source=path.with_suffix('.source');path.replace(source)
        _ffmpeg(['-i',str(source),'-frames:v','1',str(path)])
        source.unlink();suffix='.jpg'
    destination=path.with_suffix(suffix)
    if path!=destination:path.replace(destination)
    return destination


def acquire(url,directory,note,module,download,guard_duration,save):
    target,aweme,detail=_share(url)
    photo='/note/' in urlparse(target).path
    info={}
    if not detail:
        try:
            # The mobile share shell omits media. Render the resolved canonical
            # work page instead; its public page hydrates the actual detail.
            browser_url=f"https://www.douyin.com/{'note' if photo else 'video'}/{aweme}"
            info=_browser_info(browser_url,module)
            detail=info.get('detail') or {}
        except Exception as exc:
            raise ValueError('抖音分享页已展开，但浏览器未取得可读作品。可能需要登录或人工完成验证；可手动补充正文、字幕或图片文字。') from exc
    detail=detail or {}
    detail_id=str(detail.get('aweme_id') or detail.get('awemeId') or detail.get('item_id') or '')
    if detail_id and detail_id!=aweme:raise ValueError('抖音页面返回其他作品，已停止以避免解析推荐内容')
    photo=photo or bool(detail.get('images') or detail.get('image_post_info'))
    canonical=f"https://www.douyin.com/{'note' if photo else 'video'}/{aweme}"
    description=str(detail.get('desc') or info.get('metaDescription') or '')
    title=description or str(info.get('ogTitle') or info.get('title') or '抖音作品')
    data={'noteId':note,'platform':'douyin','source':url,'canonicalSource':canonical,'awemeId':aweme,
          'title':title,'description':description,'author':(detail.get('author') or {}).get('nickname',''),
          'evidence':[],'warnings':[]}
    if description:data['evidence'].append({'kind':'article','text':description,'locator':'抖音完整正文'})
    if photo:
        pictures=_pictures(detail,info)
        if not pictures:raise ValueError('已识别抖音图文作品，但页面未提供可读取配图；需要登录或手动补充图片文字')
        if len(pictures)>20:data['warnings'].append('配图超过20张，本次仅处理前20张。')
        def fetch_image(row):
            index,image=row
            path=_image(image,directory,index,download)
            return {'index':index+1,'asset':f'/media/{note}/{path.name}'}
        with ThreadPoolExecutor(max_workers=4) as pool:data['images']=list(pool.map(fetch_image,enumerate(pictures[:20])))
        data['warnings'].append('已获取抖音正文与配图，将识别图片中的食材和做法。')
    else:
        video=detail.get('video') or {}
        duration=float(video.get('duration') or 0)/1000
        if not duration and info.get('videos'):duration=info['videos'][0].get('duration') or 0
        data['duration']=guard_duration(duration)
        candidates=_urls(video.get('play_addr') or video.get('playAddr') or {})
        height=max(240,min(720,int(os.getenv('MEDIA_VIDEO_HEIGHT','480'))))
        variants=video.get('bit_rate') or video.get('bitRate') or []
        def rank_variant(item):
            addr=item.get('play_addr') or item.get('playAddr') or {}
            h=addr.get('height') or video.get('height') or 0
            return (h>height,-h if h<=height else h,item.get('bit_rate') or item.get('bitRate') or 0)
        variant_urls=[u for item in sorted(variants,key=rank_variant) for u in _urls(item.get('play_addr') or item.get('playAddr') or {})]
        candidates=list(dict.fromkeys(variant_urls+candidates))
        try:
            fallback=module.find_media_url(info)
            if fallback not in candidates:candidates.append(fallback)
        except Exception:pass
        if not candidates:raise ValueError('抖音视频页未返回可下载的视频流；可能需要登录或人工完成验证')
        for candidate in candidates:
            try:
                download(candidate,directory/'video.mp4',{'Referer':'https://www.douyin.com/','User-Agent':_UA})
                break
            except Exception:continue
        else:raise ValueError('抖音视频流下载失败，请检查网络或作品访问权限')
        data['video']=f'/media/{note}/video.mp4'
    save(directory,data)
    return data
