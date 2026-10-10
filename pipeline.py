"""Source acquisition -> validated recipes; optional incremental events."""
import os
import time
import uuid
from pathlib import Path
import ai
from ai import request_json
from contracts import SourcePost, ParseResult, evidence_id, shared_evidence
from sources import source_url, extract_source
from recipes import PROMPT, validate_recipes
import recipe_batches

RECIPE_CACHE = Path(__file__).parent/'data/recipe-cache'


def parse(payload: dict, on_event=None) -> ParseResult:
    start = time.perf_counter()
    def emit(kind, data):
        if on_event is not None:
            on_event(kind, data)

    url = source_url(payload.get('share', ''))
    post = SourcePost({'url': url})
    emit('progress', {'stage': 'source', 'message': '正在读取正文与媒体、识别图片文字…'})
    acquisition_start = time.perf_counter()
    if url:
        try:
            post = SourcePost.from_mapping(url, extract_source(url))
        except ImportError:
            post.warnings.append('本地下载依赖未安装，请按README通过虚拟环境启动；可手动补充。')
        except Exception as exc:
            post.warnings.append(str(exc) if isinstance(exc, ValueError) else
                                 '来源下载或画面读取失败，请手动补充完整内容。')
    post.timings['sourceSeconds'] = round(time.perf_counter()-acquisition_start, 3)
    # Never mutate source-cache dictionaries when adding manual evidence.
    post.evidence = list(post.evidence)
    for kind in ('article', 'subtitle', 'video_ocr', 'image_ocr'):
        value = payload.get(kind, '').strip()
        if value:
            post.evidence.append({'kind': kind, 'text': value, 'locator': '用户手动补充'})
    evidence = shared_evidence(post.evidence)
    emit('source', {'evidence': evidence, 'media': post.media, 'warnings': post.warnings})
    result = {'schemaVersion': 2, 'recipes': [], 'evidence': evidence,
              'media': post.media, 'warnings': post.warnings, 'timings': post.timings}
    if not post.evidence:
        result['warnings'] = post.warnings or ['请粘贴来源内容，或手动创建菜谱']
    else:
        key, base_url, model = ai.settings('recipe')
        if not key:
            post.warnings.append('内容已保留；尚未配置 MODEL_API_KEY，请手动建卡或配置模型后重试。')
        else:
            cards_by_batch = {}
            def completed(index, rows, batch_evidence, count, total, error):
                cards = []
                for row in rows:
                    # Independent named sections can cite their own evidence;
                    # uncertain whole-post results retain all contextual rows.
                    own = [e for e in batch_evidence if e.get('kind') != 'image_ocr' or e.get('dish') == row['name']]
                    reliable = any(e.get('kind') == 'image_ocr' for e in own) and all(e.get('standalone') is True for e in
                                               batch_evidence if e.get('kind') == 'image_ocr')
                    refs = own if reliable else batch_evidence
                    cards.append({**row, 'id': str(uuid.uuid4()), 'source': url,
                                  'evidenceIds': list(dict.fromkeys(evidence_id(e) for e in refs)),
                                  'targetServings': row['servings'], 'selected': False})
                cards_by_batch[index] = cards
                if cards:
                    post.timings.setdefault('firstRecipeSeconds', round(time.perf_counter()-start, 3))
                    emit('recipes', {'recipes': cards, 'completedGroups': count,
                                     'totalGroups': total, 'batchIndex': index})
                elif error:
                    emit('progress', {'stage': 'recipes', 'completedGroups': count,
                                      'totalGroups': total, 'warnings': [error]})

            recipe_start = time.perf_counter()
            _, timings, warnings = recipe_batches.run(post.context, post.evidence, PROMPT,
                base_url.rstrip('/')+'/chat/completions', key, model, RECIPE_CACHE,
                payload.get('refreshRecipe'), request_json, ai.response_json, validate_recipes,
                batch_size=max(1, min(4, int(os.getenv('RECIPE_BATCH_SIZE', '3')))),
                workers=max(1, min(4, int(os.getenv('RECIPE_WORKERS', '4')))), on_batch=completed)
            post.timings.update(timings)
            post.timings['recipeSeconds'] = round(time.perf_counter()-recipe_start, 3)
            post.warnings.extend(warnings)
            result['recipes'] = [card for index in sorted(cards_by_batch) for card in cards_by_batch[index]]
    post.timings['totalSeconds'] = round(time.perf_counter()-start, 3)
    return result
