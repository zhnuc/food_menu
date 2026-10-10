"""Bilibili/Douyin adapters: source -> real media -> frames -> evidence.

Bilibili DASH/subtitle flow references yyyzl/BiNote. Download/frame
fallback references bilibili-video-reader. DyNote is used for Douyin browser
page collection. See THIRD_PARTY.md.
"""
import hashlib
import importlib.util
import json
import math
import os
import re
import subprocess
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse, urlencode
from urllib.request import Request, ProxyHandler, HTTPRedirectHandler, build_opener

import vision
import bilinote_adapter

ROOT=Path(__file__).parent
DATA=ROOT/'data'
UA='Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 Chrome/130.0 Mobile Safari/537.36'
_locks={}
_locks_guard=threading.Lock()
MEDIA_DOMAINS=('bilivideo.com','bilivideo.cn','hdslb.com','bilibili.com','douyinvod.com',
               'douyin.com','iesdouyin.com','douyinpic.com','byteimg.com','ibytedtos.com','bytecdn.cn','amemv.com','snssdk.com')


def _host_allowed(url,domains):
    p=urlparse(url)
    try:port=p.port
    except ValueError:return False
    host=(p.hostname or '').lower()
    return p.scheme in ('http','https') and not p.username and not p.password and port in (None,80,443) and any(host==d or host.endswith('.'+d) for d in domains)


def platform(url):
    if _host_allowed(url,('bilibili.com','b23.tv')):return 'bilibili'
    if _host_allowed(url,('douyin.com','iesdouyin.com')):return 'douyin'
    return ''


class SafeRedirect(HTTPRedirectHandler):
    def __init__(self,domains):super().__init__();self.domains=domains
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        if not _host_allowed(newurl,self.domains):raise ValueError('平台跳转到非支持地址，已停止')
        return super().redirect_request(req,fp,code,msg,headers,newurl)


def _open(url,headers=None,domains=MEDIA_DOMAINS,timeout=35):
    if not _host_allowed(url,domains):raise ValueError('媒体地址不是支持的平台或 CDN')
    # Chinese public sharing pages use a direct connection; don't inherit
    # a global VPN route that previously broke local share-page extraction.
    return build_opener(ProxyHandler({}),SafeRedirect(domains)).open(
        Request(url,headers={'User-Agent':UA,**(headers or {})}),timeout=timeout)


def _json(url,headers=None):
    with _open(url,headers,('bilibili.com','hdslb.com'),25) as response:
        raw=response.read(2_000_001)
    if len(raw)>2_000_000:raise ValueError('平台字幕或元数据超过读取上限')
    return json.loads(raw.decode('utf-8-sig'))


def _download(url,path,headers=None,limit=100_000_000):
    if path.exists() and path.stat().st_size:return path
    temporary=path.with_suffix(path.suffix+'.part')
    try:
        with _open(url,headers,timeout=60) as response,temporary.open('wb') as output:
            if int(response.headers.get('Content-Length','0'))>limit:raise ValueError('媒体超过处理体积上限')
            size=0
            while chunk:=response.read(65536):
                size+=len(chunk)
                if size>limit:raise ValueError('媒体超过处理体积上限')
                output.write(chunk)
        if not size:raise ValueError('媒体为空，下载未完成')
        temporary.replace(path)
    finally:
        if temporary.exists():temporary.unlink()
    return path


def _download_stream(streams,path,headers,limit=100_000_000):
    for stream in streams:
        urls=[stream.get('baseUrl') or stream.get('base_url')]
        urls.extend(stream.get('backupUrl') or stream.get('backup_url') or [])
        for url in filter(None,urls):
            try:return _download(url,path,headers,limit)
            except Exception:continue
    raise ValueError('平台音视频 CDN 下载失败，主地址和备用地址均不可用')


def _save(directory,data):
    temporary=directory/'extracted.tmp'
    temporary.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    temporary.replace(directory/'extracted.json')


def _duration(value):
    duration=float(value or 0)
    if not math.isfinite(duration) or not 0<duration<=300:
        raise ValueError('当前视频处理上限为5分钟；时长未知或超长的视频请补充字幕')
    return duration


def _ffmpeg(args):
    import imageio_ffmpeg
    result=subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-nostdin','-loglevel','error','-y',*args],
                          capture_output=True,timeout=90)
    if result.returncode:raise ValueError('视频或关键帧处理失败，请检查原视频文件')


def _frames(directory,data):
    video=directory/'video.mp4'
    if not video.exists():return
    interval=max(max(2,min(6,int(os.getenv('VIDEO_FRAME_INTERVAL','3')))),math.ceil(data['duration']/30))
    profile=f'continuous-v1:{interval}:960'
    if data.get('frameProfile')==profile and data.get('frames') and all((directory/Path(f['asset']).name).exists() for f in data['frames']):return
    seconds=list(range(0,math.ceil(data['duration']),interval))
    # Decode once instead of starting and seeking a new FFmpeg for each frame.
    _ffmpeg(['-i',str(video),'-an','-vf',f"select='gte(t,selected_n*{interval})',scale=w='min(iw,960)':h='min(ih,960)':force_original_aspect_ratio=decrease",
             '-fps_mode','vfr','-frames:v',str(len(seconds)),'-q:v','3','-start_number','0',str(directory/'sample-%03d.jpg')])
    frames=[]
    for index,second in enumerate(seconds):
        sample=directory/f'sample-{index:03}.jpg'
        if not sample.exists():break
        path=directory/f'frame-{second:02}.jpg'
        sample.replace(path)
        frames.append({'time':second,'asset':f"/media/{data['noteId']}/{path.name}"})
    if not frames:raise ValueError('未取得可识别的视频帧')
    # New frame assets invalidate previous OCR, even if the model is unchanged.
    data['evidence']=[e for e in data.get('evidence',[]) if e.get('kind') not in ('video_ocr','frame')]
    data.pop('visionProcessed',None);data.pop('visionAssets',None)
    data['frames']=frames
    data['frameProfile']=profile
    data['video']=f"/media/{data['noteId']}/video.mp4"


def _bili(url,directory,note,expand_bili):
    target=expand_bili(url) if urlparse(url).hostname=='b23.tv' else url
    bv=re.search(r'BV[0-9A-Za-z]{10}',target)
    av=re.search(r'(?:/video/)?av(\d+)',target)
    if not bv and not av:raise ValueError('未从B站链接识别到 BV/AV 编号')
    headers={'Referer':'https://www.bilibili.com/',
             'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130.0 Safari/537.36'}
    warnings=[]
    view=_json('https://api.bilibili.com/x/web-interface/view?'+urlencode(
        {'bvid':bv.group()} if bv else {'aid':av.group(1)}),headers)
    if view.get('code')!=0:raise ValueError('B站视频信息获取失败')
    view=view['data'];pages=view.get('pages') or [{'cid':view['cid'],'duration':view['duration']}]
    page_number=int(parse_qs(urlparse(target).query).get('p',['1'])[0])
    if not 1<=page_number<=len(pages):raise ValueError('B站链接指定的分P不存在')
    page=pages[page_number-1];duration=_duration(page.get('duration') or view['duration'])
    data={'noteId':note,'platform':'bilibili','source':url,'canonicalSource':f"https://www.bilibili.com/video/{view['bvid']}/?p={page_number}",
          'bvid':view['bvid'],'cid':page['cid'],'title':view['title'],'author':view.get('owner',{}).get('name',''),
          'duration':duration,'evidence':[],'warnings':warnings}
    if len(pages)>1:data['warnings'].append(f'本次处理第 {page_number} P；其他分P需单独添加。')
    if view.get('desc') and view['desc'].strip()!='-':
        data['evidence'].append({'kind':'article','text':view['desc'],'locator':'B站完整简介'})
    query=urlencode({'bvid':view['bvid'],'aid':view['aid'],'cid':page['cid']})
    play=_json('https://api.bilibili.com/x/player/playurl?'+query+'&fnval=16&qn=32',headers)
    dash=(play.get('data') or {}).get('dash') or {}
    height=max(240,min(720,int(os.getenv('MEDIA_VIDEO_HEIGHT','480'))))
    streams=sorted(dash.get('video') or [],key=lambda v:(v.get('height',0)>height,-v.get('height',0) if v.get('height',0)<=height else v.get('height',0),not v.get('codecs','').startswith('avc'),v.get('bandwidth',0)))
    try:
        if play.get('code')!=0 or not streams:raise ValueError('平台未返回画面流')
        _download_stream(streams,directory/'video.m4s',headers)
        _ffmpeg(['-i',str(directory/'video.m4s'),'-an','-c:v','copy',str(directory/'video.mp4')])
    except Exception:
        try:
            bilinote_adapter.download(data['canonicalSource'],directory,headers)
            data['warnings'].append('通过BiliNote的yt-dlp兼容下载路线取得视频。')
        except Exception as exc:raise ValueError('B站视频下载失败，BiliNote备用路线也失败；可能需要登录') from exc
    _save(directory,data)
    return data


def _dynote_module():
    path=ROOT/'vendor/dynote/extract_douyin_text.py'
    if not path.exists():raise ValueError('DyNote 源码未安装，请检查 vendor/dynote')
    spec=importlib.util.spec_from_file_location('food_menu_dynote',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def _douyin(url,directory,note):
    from douyin_media import acquire
    return acquire(url,directory,note,_dynote_module(),_download,_duration,_save)


def extract(url,vision_key='',vision_url='',vision_model='',request_json=None,expand_bili=None):
    kind=platform(url)
    if not kind:raise ValueError('不是支持的B站或抖音来源')
    note=hashlib.sha256((kind+':'+url).encode()).hexdigest()[:24]
    directory=DATA/note;directory.mkdir(parents=True,exist_ok=True)
    with _locks_guard:lock=_locks.setdefault(note,threading.Lock())
    with lock:
        acquire_start=time.perf_counter()
        cached=directory/'extracted.json'
        cache_hit=cached.exists()
        if cached.exists():data=json.loads(cached.read_text(encoding='utf-8'))
        else:data=_bili(url,directory,note,expand_bili) if kind=='bilibili' else _douyin(url,directory,note)
        # Historical ASR remains archived on disk, but never enters new cards.
        data['evidence']=[e for e in data['evidence'] if e.get('kind')!='transcript']
        data.pop('transcribed',None)
        data['warnings']=[w for w in data.get('warnings',[]) if not any(word in w for word in ['语音','音轨','转录','字幕','人声'])]
        if not data.get('images') and not (directory/'video.mp4').exists():
            data=_bili(url,directory,note,expand_bili) if kind=='bilibili' else _douyin(url,directory,note)
        timings={'acquireSeconds':round(time.perf_counter()-acquire_start,3),'mediaCacheHit':cache_hit}
        frame_start=time.perf_counter()
        _frames(directory,data)
        timings['framesSeconds']=round(time.perf_counter()-frame_start,3)
        data['_timings']=timings
        data['warnings']=list(dict.fromkeys(data.get('warnings',[])))
        _save(directory,data)
        return vision.enrich_visuals(data,directory,vision_key,vision_url,vision_model,request_json)
