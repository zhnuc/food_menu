"""Shared API configuration with optional model choices for each stage."""
import json
import os
import time
from contextvars import ContextVar
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).parent
usage_observer=ContextVar('ai_usage_observer',default=None)
for line in (ROOT / '.env').read_text(encoding='utf-8-sig').splitlines() if (ROOT / '.env').exists() else []:
    if '=' in line and not line.strip().startswith('#'):
        name, value = line.split('=', 1)
        os.environ.setdefault(name.strip(), value.strip())


def settings(stage=''):
    model = os.getenv('MODEL_NAME', 'gemini-3.8-flash-low')
    if stage in ('vision', 'recipe'):
        model = os.getenv(stage.upper() + '_MODEL_NAME', '').strip() or model
    return (os.getenv('MODEL_API_KEY', ''),
            os.getenv('MODEL_BASE_URL', 'http://127.0.0.1:3000/v1'),
            model)


def _request_json(url, body=None, token='', timeout=45):
    request = Request(url, data=json.dumps(body).encode() if body is not None else None,
        headers={'Content-Type': 'application/json', 'User-Agent': 'Mozilla/5.0',
                 **({'Authorization': 'Bearer ' + token} if token else {})})
    local_gateway = urlparse(url).hostname in ('localhost', '127.0.0.1')
    for attempt in range(3):
        try:
            with urlopen(request, timeout=timeout) as response:
                raw = response.read(2_000_001)
            break
        except HTTPError as exc:
            # AIClient2API briefly removes its sole provider during token refresh.
            # Retry only that explicit rejection, never ambiguous generation errors.
            if not local_gateway or exc.code != 500 or attempt == 2:
                raise
            if b'No healthy provider found' not in exc.read(16384):
                raise
            time.sleep(attempt + 1)
    if len(raw) > 2_000_000:
        raise ValueError('模型返回内容过大')
    return json.loads(raw)


def request_json(url, body=None, token='', timeout=45):
    start=time.perf_counter();result=None
    try:
        result=_request_json(url,body,token,timeout)
        return result
    finally:
        observer=usage_observer.get()
        if observer:
            usage=result.get('usage',{}) if isinstance(result,dict) else {}
            valid=lambda value:value if isinstance(value,int) and not isinstance(value,bool) and value>=0 else None
            observer({'model':str((body or {}).get('model',''))[:200],'succeeded':result is not None,
                'inputTokens':valid(usage.get('prompt_tokens')),'outputTokens':valid(usage.get('completion_tokens')),
                'elapsed':round(time.perf_counter()-start,3)})


def response_json(result):
    raw = result['choices'][0]['message']['content'].strip()
    if raw.startswith('```') and raw.endswith('```'):
        raw = raw.split('\n', 1)[1].rsplit('```', 1)[0].strip()
    return json.loads(raw)
