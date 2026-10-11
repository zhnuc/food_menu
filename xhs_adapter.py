"""Adapt public mobile share state to yt-dlp's existing XHS media extractor."""
import copy
import json
import math
import re
from yt_dlp.extractor.xiaohongshu import XiaoHongShuIE
from yt_dlp.utils import js_to_json


def normalize_state(state, note_id):
    legacy = state.get('note', {}).get('noteDetailMap', {}).get(note_id, {}).get('note')
    mobile = state.get('noteData', {}).get('data', {}).get('noteData')
    note = legacy if isinstance(legacy, dict) and legacy else mobile
    if not isinstance(note, dict) or not note or note.get('noteId', note_id) != note_id:
        raise ValueError('小红书未返回这篇笔记的公开内容；可能需要登录或笔记已不可访问，请补充图片或正文')
    note = copy.deepcopy(note)
    # Mobile H5 uses infoList; one full-size URL per original picture.
    for image in note.get('imageList') or []:
        if not image.get('urlDefault'):
            variants = image.get('infoList') or []
            detail = next((row.get('url') for row in variants
                           if row.get('imageScene') in ('H5_DTL', 'WB_DFT') and row.get('url')), None)
            image['urlDefault'] = detail or image.get('url') or next((row.get('url') for row in variants if row.get('url')), '')
    adapted = dict(state)
    adapted['note'] = {'noteDetailMap': {note_id: {'note': note}}}
    return adapted, note


class PublicShareXHSIE(XiaoHongShuIE):
    @classmethod
    def ie_key(cls):
        # Replace the default instance instead of registering a lower-priority IE.
        return 'XiaoHongShu'

    def _download_webpage(self, url, video_id, *args, **kwargs):
        html = super()._download_webpage(url, video_id, *args, **kwargs)
        match = re.search(r'window\.__INITIAL_STATE__\s*=\s*(\{.*?\})\s*</script>', html, re.S)
        if not match:
            raise ValueError('小红书页面没有返回可读取的笔记数据，请补充图片或正文')
        state = json.loads(js_to_json(match.group(1)))
        state, self._public_note = normalize_state(state, video_id)
        encoded = json.dumps(state, ensure_ascii=False).replace('<', r'\u003c')
        return html[:match.start(1)] + encoded + html[match.end(1):]

    def _real_extract(self, url):
        self._public_note = {}
        info = super()._real_extract(url)
        if not info.get('duration'):
            durations = [f.get('duration') for f in info.get('formats') or []]
            durations.append(self._public_note.get('video', {}).get('media', {}).get('video', {}).get('duration'))
            durations = [d for d in durations if isinstance(d, (int, float)) and not isinstance(d, bool) and math.isfinite(d) and d > 0]
            if durations:
                info['duration'] = max(durations)
        user = self._public_note.get('user') or {}
        info['uploader'] = user.get('nickname') or user.get('nickName')
        return info
