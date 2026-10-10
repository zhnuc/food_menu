import pipeline
import sources
import recipes as recipes_domain
import vision
import tempfile
import unittest
from PIL import Image
from pathlib import Path
from unittest.mock import patch
import douyin_media
import local_media
import video_media


class MediaTests(unittest.TestCase):
    def test_continuous_frames_keep_sample_order_and_invalidate_old_ocr(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp)
            for index,color in enumerate(['red']*3+['green']*3+['blue']):
                Image.new('RGB',(1200,600),color).save(directory/f'color-{index:02}.png')
            video_media._ffmpeg(['-framerate','1','-i',str(directory/'color-%02d.png'),'-c:v','libx264','-pix_fmt','yuv420p',str(directory/'video.mp4')])
            data={'duration':7,'noteId':'test','frames':[{'time':0,'asset':'/media/test/old.jpg'}],'visionProcessed':True,'visionAssets':['old'],'evidence':[{'kind':'article','text':'正文'},{'kind':'video_ocr','text':'旧识别'}]}
            with patch('video_media._ffmpeg',wraps=video_media._ffmpeg) as decode:
                video_media._frames(directory,data)
                video_media._frames(directory,data)
                self.assertEqual(decode.call_count,1)
            self.assertEqual([frame['time'] for frame in data['frames']],[0,3,6])
            self.assertEqual(data['evidence'],[{'kind':'article','text':'正文'}])
            self.assertNotIn('visionProcessed',data)
            for frame,color in zip(data['frames'],['red','green','blue']):
                with Image.open(directory/Path(frame['asset']).name) as image:
                    self.assertEqual(image.size,(960,480))
                    expected=Image.new('RGB',(1,1),color).getpixel((0,0))
                    self.assertLess(max(abs(a-b) for a,b in zip(image.getpixel((100,100)),expected)),12)

    def test_cdn_and_source_hosts_are_bounded(self):
        self.assertEqual(video_media.platform('https://b23.tv/abc'),'bilibili')
        for url in ['https://user:pass@bilibili.com/', 'http://127.0.0.1/', 'https://douyin.com.evil.test/', 'https://douyin.com:9000/']:
            self.assertEqual(video_media.platform(url),'')
        with self.assertRaises(ValueError):
            video_media.SafeRedirect(video_media.MEDIA_DOMAINS).redirect_request(None,None,302,'',{},'http://127.0.0.1/private')

    def test_cdn_backup_after_failure(self):
        with patch('video_media._download',side_effect=[ValueError('403'),Path('audio.m4a')]) as download:
            result=video_media._download_stream([{'baseUrl':'https://a.bilivideo.com/main','backupUrl':['https://b.bilivideo.com/backup']}],Path('audio.m4a'),{})
            self.assertEqual(result,Path('audio.m4a'))
            self.assertIn('/backup',download.call_args.args[0])

    def test_photo_images_exclude_recommendations(self):
        detail={'images':[{'url_list':['https://p.douyinpic.com/actual.jpg']}]}
        self.assertEqual(douyin_media._pictures(detail,{'visibleImages':['https://p.douyinpic.com/recommendation.jpg']}),['https://p.douyinpic.com/actual.jpg'])
        self.assertEqual(douyin_media._pictures({}, {'visibleImages':['https://p.douyinpic.com/recommendation.jpg']}),[])

    def test_cached_transcript_is_excluded_from_visual_flow(self):
        import hashlib,json
        url='https://b23.tv/test'
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);directory=root/hashlib.sha256(('bilibili:'+url).encode()).hexdigest()[:24];directory.mkdir()
            (directory/'video.mp4').write_bytes(b'cached media')
            (directory/'extracted.json').write_text(json.dumps({'evidence':[{'kind':'transcript','text':'错误转录'},{'kind':'article','text':'正文'}],'duration':10,'warnings':['语音转录失败'],'transcribed':True}),encoding='utf-8')
            with patch('video_media.DATA',root),patch('video_media._bili') as acquire,patch('video_media._frames'),patch('video_media.vision.enrich_visuals',side_effect=lambda data,*args:data):
                result=video_media.extract(url)
            self.assertEqual(result['evidence'],[{'kind':'article','text':'正文'}])
            self.assertEqual(result['warnings'],[])
            acquire.assert_not_called()

    @patch.dict(local_media.os.environ,{'VISION_BATCH_SIZE':'1'})
    def test_failed_ocr_preserves_article_and_retries_only_failed_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp)
            for name in ['image-00.jpg','image-01.jpg']:Image.new('RGB',(80,120),'white').save(directory/name)
            data={'evidence':[{'kind':'article','text':'番茄炒熟'}],'warnings':[], 'images':[{'index':1,'asset':'/media/test/image-00.jpg'},{'index':2,'asset':'/media/test/image-01.jpg'}]}
            response={'choices':[{'message':{'content':'{"items":[{"id":0,"text":"番茄300克"}]}'}}]}
            from unittest.mock import Mock
            request=Mock(return_value=response)
            vision.enrich_visuals(data,directory,'key','https://example.com/v1','vision',request)
            self.assertEqual(data['evidence'][0]['kind'],'article')
            self.assertEqual(len(data['visionAssets']),1)
            self.assertFalse(data['visionProcessed'])
            request=Mock(return_value={'choices':[{'message':{'content':'{"text":"盐适量"}'}}]})
            vision.enrich_visuals(data,directory,'key','https://example.com/v1','vision',request)
            self.assertEqual(request.call_count,1)
            self.assertTrue(data['visionProcessed'])

    def test_douyin_mismatched_work_is_rejected(self):
        with patch('douyin_media._share',return_value=('https://www.douyin.com/video/12345678901','12345678901',{'aweme_id':'12345678902','video':{}})):
            with self.assertRaisesRegex(ValueError,'其他作品'):
                douyin_media.acquire('https://v.douyin.com/test',Path('.'),'note',None,None,None,None)
