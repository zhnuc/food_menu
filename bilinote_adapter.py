"""Reuse JefferyHcool/BiliNote's Bilibili downloader compatibility layer.

The full application emits Markdown notes; this adapter only retrieves actual
media so this cookbook can retain its own evidence and recipe JSON contract.
Upstream source and its MIT license are retained in vendor/bilinote.
"""
import importlib.util
import os
import threading
from pathlib import Path

ROOT=Path(__file__).parent
UPSTREAM=ROOT/'vendor/bilinote'
_patch_lock=threading.Lock()


class QuietLogger:
    def debug(self,message):pass
    def info(self,message):pass
    def warning(self,message):pass
    def error(self,message):pass


def _patch():
    path=UPSTREAM/'bilibili_dm_patch.py'
    if not path.exists():raise ValueError('BiliNote 下载适配源码未安装')
    with _patch_lock:
        spec=importlib.util.spec_from_file_location('food_menu_bilinote_dm',path)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        return module.apply_bilibili_dm_img_patch()


def download(url,directory,headers):
    import imageio_ffmpeg
    import yt_dlp
    _patch()
    options={'quiet':True,'noprogress':True,'logger':QuietLogger(),'noplaylist':True,
        'socket_timeout':30,'retries':3,'fragment_retries':3,'http_headers':headers,
        'max_filesize':100_000_000,'ffmpeg_location':imageio_ffmpeg.get_ffmpeg_exe(),
        'format':f"bv[ext=mp4][height<={max(240,min(720,int(os.getenv('MEDIA_VIDEO_HEIGHT','480'))))}]/b[height<=480]/b",
        'merge_output_format':'mp4','outtmpl':str(directory/'video.%(ext)s')}
    with yt_dlp.YoutubeDL(options) as downloader:
        info=downloader.extract_info(url,download=False)
        duration=float(info.get('duration') or 0)
        if not 0<duration<=300:raise ValueError('BiliNote备用下载只处理5分钟以内的视频')
        downloader.download([url])
    video=directory/'video.mp4'
    if not video.exists():raise ValueError('BiliNote备用下载未产生完整视频')
    return video
