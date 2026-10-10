"""XHS public share extraction. No browser cookies are read or copied."""
import hashlib, json, re, os, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse,parse_qs
from urllib.request import Request,build_opener,HTTPRedirectHandler
from vision import enrich_visuals
ROOT=Path(__file__).parent
DATA=ROOT/'data'
DOMAINS=('xiaohongshu.com','xhslink.cn','xhslink.com')
def allowed(url):
    p=urlparse(url);host=p.hostname or ''
    return p.scheme in ('http','https') and not p.username and not p.password and p.port in (None,80,443) and any(host==d or host.endswith('.'+d) for d in DOMAINS)
class Redirect(HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        if not allowed(newurl):raise ValueError('小红书短链接跳转到非支持站点，已停止')
        return super().redirect_request(req,fp,code,msg,headers,newurl)
class ImageRedirect(HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        host=urlparse(newurl).hostname or ''
        if not (host=='xhscdn.com' or host.endswith('.xhscdn.com')):raise ValueError('小红书图片跳转到非图片站点，已停止')
        return super().redirect_request(req,fp,code,msg,headers,newurl)
def resolve(url):
    if not allowed(url):raise ValueError('小红书链接无效')
    with build_opener(Redirect).open(Request(url,headers={'User-Agent':'Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 Chrome/130.0 Mobile Safari/537.36'}),timeout=25) as response:
        final=response.url
    target=parse_qs(urlparse(final).query).get('redirectPath',[''])[0] if urlparse(final).path=='/login' else final
    target=target.replace('http://','https://',1)
    if not allowed(target):raise ValueError('平台要求登录，无法取得可解析的笔记地址')
    match=re.search(r'/(?:discovery/item|explore)/([a-f0-9]{24})(?:[/?]|$)',target)
    if not match:raise ValueError('无法从分享页解析笔记ID')
    return target,match.group(1)
def _download_image(url, path):
    host=urlparse(url).hostname or ''
    if not (host=='xhscdn.com' or host.endswith('.xhscdn.com')):
        raise ValueError('图文笔记包含非小红书图片地址，已停止下载')
    req=Request(url,headers={'User-Agent':'Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 Chrome/130.0 Mobile Safari/537.36','Referer':'https://www.xiaohongshu.com/'})
    with build_opener(ImageRedirect()).open(req,timeout=25) as response:
        content_type=response.headers.get_content_type()
        if content_type not in ('image/jpeg','image/png','image/webp'):
            raise ValueError('图文笔记返回的材料不是支持的图片格式')
        raw=response.read(15_000_001)
    if not raw or len(raw)>15_000_000:
        raise ValueError('图片为空或超过15MB处理上限')
    path=path.with_suffix({'image/jpeg':'.jpg','image/png':'.png','image/webp':'.webp'}[content_type])
    path.write_bytes(raw)
    return path

def extract(url,vision_key='',vision_url='',vision_model='',request_json=None):
    import yt_dlp
    from video_media import _frames
    acquire_start=time.perf_counter()
    target,note=resolve(url);directory=DATA/note;directory.mkdir(parents=True,exist_ok=True)
    cached=directory/'extracted.json'
    cache_hit=cached.exists()
    if cached.exists():data=json.loads(cached.read_text(encoding='utf-8'))
    else:
        height=max(240,min(720,int(os.getenv('MEDIA_VIDEO_HEIGHT','480'))))
        opts={'quiet':True,'noprogress':True,'socket_timeout':25,'retries':0,'noplaylist':True,'max_filesize':100_000_000,'outtmpl':str(directory/'video.%(ext)s'),'format':f'bv[height<={height}]/b[height<={height}]/best','ignore_no_formats_error':True}
        with yt_dlp.YoutubeDL(opts) as engine:
            info=engine.extract_info(target,download=False)
            if info.get('extractor_key')!='XiaoHongShu':raise ValueError('平台未返回可用的小红书内容')
            if not info.get('formats'):
                thumbnails=[];seen=set()
                for thumb in info.get('thumbnails') or []:
                    image_url=thumb.get('url')
                    if image_url and image_url not in seen:
                        seen.add(image_url);thumbnails.append(image_url)
                if not thumbnails:raise ValueError('未提取到视频或配图；请手动补充正文、字幕或图片文字')
                if len(thumbnails)>20:thumbnails=thumbnails[:20]
                (directory/'metadata.json').write_text(json.dumps(engine.sanitize_info(info),ensure_ascii=False,indent=2),encoding='utf-8')
                evidence=[]
                if info.get('description'):evidence.append({'kind':'article','text':info['description'],'locator':'平台完整正文'})
                images=[]
                def fetch_image(row):
                    i,image_url=row;frame=_download_image(image_url,directory/f'image-{i:02}')
                    return {'index':i+1,'asset':f'/media/{note}/{frame.name}'}
                with ThreadPoolExecutor(max_workers=4) as pool:images=list(pool.map(fetch_image,enumerate(thumbnails)))
                data={'noteId':note,'source':url,'evidence':evidence,'images':images,'warnings':['已获取正文与配图；图片文字尚待识别。']}
                cached.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
            else:
                duration=info.get('duration') or 0
                if not 0<duration<=300:raise ValueError('当前处理时长上限为5分钟；无法确定时长的内容请手动补充')
                if (info.get('filesize') or 0)>100_000_000:raise ValueError('视频超过100MB处理上限')
                # Reuse extracted metadata instead of fetching the page again.
                info=engine.process_ie_result(info,download=True)
                video=Path(engine.prepare_filename(info))
                if not video.exists():raise ValueError('视频下载未完成')
                (directory/'metadata.json').write_text(json.dumps(engine.sanitize_info(info),ensure_ascii=False,indent=2),encoding='utf-8')
                evidence=[]
                if info.get('description'):evidence.append({'kind':'article','text':info['description'],'locator':'平台完整正文'})
                data={'noteId':note,'source':url,'evidence':evidence,'video':f'/media/{note}/{video.name}','duration':duration,'warnings':[]}
                cached.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    data['_timings']={'acquireSeconds':round(time.perf_counter()-acquire_start,3),'mediaCacheHit':cache_hit}
    frame_start=time.perf_counter()
    if data.get('duration'):_frames(directory,data)
    data['_timings']['framesSeconds']=round(time.perf_counter()-frame_start,3)
    # Older cache entries predate explicit source metadata.
    metadata=directory/'metadata.json'
    if metadata.exists():
        info=json.loads(metadata.read_text(encoding='utf-8'))
        data.update(platform='xiaohongshu',title=info.get('title',''),author=info.get('uploader',''),description=info.get('description',''))
    data['evidence']=[e for e in data['evidence'] if e.get('kind')!='transcript']
    data['warnings']=[w for w in data.get('warnings',[]) if '音频转写' not in w]
    return enrich_visuals(data,directory,vision_key,vision_url,vision_model,request_json)

