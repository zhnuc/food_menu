"""Platform routing and short-link expansion."""
import re
from urllib.parse import urlparse
from urllib.request import Request, HTTPRedirectHandler, build_opener
import ai
from ai import request_json
import local_media
import video_media

def source_url(text):
    found=re.search(r'https?://[^\s<>]+',text)
    if not found:
        identifier=re.fullmatch(r'\s*(BV[0-9A-Za-z]{10}|av\d+)\s*',text)
        return 'https://www.bilibili.com/video/'+identifier[1]+'/' if identifier else ''
    url=found.group().rstrip('，。；！）)')
    host=(urlparse(url).hostname or '').lower()
    if not any(host==d or host.endswith('.'+d) for d in ['bilibili.com','b23.tv','douyin.com','iesdouyin.com','xiaohongshu.com','xhslink.com','xhslink.cn']):
        raise ValueError('目前仅支持小红书、抖音和哔哩哔哩链接')
    return url


class BiliRedirect(HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        host=(urlparse(newurl).hostname or '').lower()
        if not (host=='b23.tv' or host=='bilibili.com' or host.endswith('.bilibili.com')):
            raise ValueError('B站短链接跳转到非支持站点，已停止')
        return super().redirect_request(req,fp,code,msg,headers,newurl)


def expand_bili(url):
    if (urlparse(url).hostname or '').lower()!='b23.tv': return url
    with build_opener(BiliRedirect).open(Request(url,headers={'User-Agent':'Mozilla/5.0'}),timeout=25) as response:
        target=response.url
    if not re.search(r'BV[0-9A-Za-z]+',target): raise ValueError('B站短链接已打开，但无法识别视频编号')
    return target


def extract_source(url):
    """One acquisition entry point shared by the web API and future clients."""
    args=(url,*ai.settings('vision'),request_json)
    if local_media.allowed(url):return local_media.extract(*args)
    if video_media.platform(url):return video_media.extract(*args,expand_bili=expand_bili)
    raise ValueError('不支持此平台，请补充正文或图片文字。')


