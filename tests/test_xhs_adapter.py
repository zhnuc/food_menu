import copy
import json
import unittest
from unittest.mock import patch
import yt_dlp
from yt_dlp.extractor.xiaohongshu import XiaoHongShuIE
from xhs_adapter import PublicShareXHSIE, normalize_state
from local_media import video_format

NOTE='a'*24


class XHSAdapterTests(unittest.TestCase):
    def note(self):
        return {'noteId':NOTE,'title':'虾的做法','desc':'虾仁切碎','user':{'nickname':'作者'},
                'imageList':[{'infoList':[{'imageScene':'H5_PRV','url':'https://p.xhscdn.com/preview.jpg'},
                                          {'imageScene':'H5_DTL','url':'https://p.xhscdn.com/detail.jpg'}]}],
                'video':{'media':{'video':{'duration':120},'stream':{'h264':[{'masterUrl':'https://v.xhscdn.com/video.mp4','duration':119867,'width':480,'height':720}]}}}}

    def test_mobile_note_preserves_media_text_and_ignores_recommendations(self):
        state={'noteData':{'data':{'noteData':self.note(),'widgets':[{'title':'无关菜谱'}]}}}
        before=copy.deepcopy(state)
        adapted,note=normalize_state(state,NOTE)
        self.assertEqual(note['imageList'][0]['urlDefault'],'https://p.xhscdn.com/detail.jpg')
        self.assertEqual(note['desc'],'虾仁切碎')
        self.assertEqual(set(adapted['note']['noteDetailMap']),{NOTE})
        self.assertEqual(state,before)

    def test_legacy_state_keeps_existing_original_images(self):
        note=self.note();note['imageList']=[{'urlDefault':'https://p.xhscdn.com/original.jpg'}]
        _,result=normalize_state({'note':{'noteDetailMap':{NOTE:{'note':note}}}},NOTE)
        self.assertEqual(result['imageList'],note['imageList'])

    def test_missing_or_mismatched_note_is_an_explicit_error(self):
        for state in ({'noteData':{'hasError':True}}, {'noteData':{'data':{'noteData':{**self.note(),'noteId':'b'*24}}}}):
            with self.assertRaises(ValueError):normalize_state(state,NOTE)

    def test_registered_extractor_reads_mobile_video_and_duration(self):
        html='<script>window.__INITIAL_STATE__='+json.dumps({'noteData':{'data':{'noteData':self.note()}}})+'</script>'
        with yt_dlp.YoutubeDL({'quiet':True}) as engine, patch.object(XiaoHongShuIE,'_download_webpage',return_value=html):
            engine.add_info_extractor(PublicShareXHSIE())
            info=engine.extract_info('https://www.xiaohongshu.com/discovery/item/'+NOTE,download=False)
        self.assertEqual(info['extractor_key'],'XiaoHongShu')
        self.assertEqual(info['title'],'虾的做法')
        self.assertEqual(info['description'],'虾仁切碎')
        self.assertGreater(info['duration'],119)
        self.assertLessEqual(info['duration'],120)
        self.assertEqual(info['formats'][0]['url'],'https://v.xhscdn.com/video.mp4')

    def test_large_original_does_not_hide_a_bounded_stream(self):
        with yt_dlp.YoutubeDL({'quiet':True,'format':video_format(480)}) as engine:
            result=engine.process_ie_result({'id':NOTE,'title':'虾','formats':[
                {'url':'https://v.xhscdn.com/small.mp4','filesize':33_000_000,'height':720,'quality':0},
                {'url':'https://v.xhscdn.com/original.mp4','filesize':130_000_000,'height':1080,'quality':1}]},download=False)
        self.assertEqual(result['url'],'https://v.xhscdn.com/small.mp4')
