"""Real HTTP/model regression, reusing media/OCR but refreshing recipe output."""
import json
from pathlib import Path
import sys
import time
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from compare_recipe_routes import check_quality


def main():
    previous = json.loads((ROOT / 'validation/safe-route-photo-http.json').read_text(encoding='utf-8'))
    body = {'share': previous['recipes'][0]['source'], 'refreshRecipe': True}
    request = Request('http://127.0.0.1:8767/api/parse',
        data=json.dumps(body).encode(),
        headers={'Content-Type': 'application/json', 'Accept': 'application/x-ndjson'})
    start = time.perf_counter()
    events = []
    with urlopen(request, timeout=180) as response:
        for line in response:
            event = json.loads(line)
            seconds = round(time.perf_counter() - start, 3)
            events.append({'receivedSeconds': seconds, **event})
            print(json.dumps({'type': event['type'], 'seconds': seconds,
                'cards': len(event.get('recipes', []))}, ensure_ascii=False), flush=True)
    cards = [card for event in events for card in event.get('recipes', [])]
    evidence = next(event['evidence'] for event in events if event['type'] == 'source')
    done = next(event for event in events if event['type'] == 'done')
    quality = check_quality('twelve_dishes', cards)
    quality['sharedReferences'] = all(set(card['evidenceIds']) <= {e['id'] for e in evidence} for card in cards)
    quality['noRepeatedEvidence'] = all('evidence' not in card for card in cards)
    quality['doneDoesNotResend'] = 'recipes' not in done and 'evidence' not in done
    if not all(quality.values()):
        print('Failed checks: ' + ', '.join(k for k, v in quality.items() if not v), flush=True)
    # Equivalent contents, contrasting current references with previous per-card copies.
    current = {'recipes': cards, 'evidence': evidence}
    raw_evidence = [{k: v for k, v in e.items() if k != 'id'} for e in evidence]
    old_cards = [{**{k: v for k, v in card.items() if k != 'evidenceIds'}, 'evidence': raw_evidence} for card in cards]
    legacy = {'recipes': old_cards, 'evidence': raw_evidence}
    size = lambda value: len(json.dumps(value, ensure_ascii=False).encode())
    measurements = {'currentBytes': size(current), 'equivalentLegacyBytes': size(legacy),
        'reductionPercent': round((1 - size(current) / size(legacy)) * 100, 1)}
    report = {'scope': 'Real model recipe regeneration; existing media/vision caches may be reused.',
        'events': events, 'quality': quality, 'payloadComparison': measurements}
    (ROOT / 'validation/live-stream-check.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'timings': done['timings'], 'qualityPass': all(quality.values()),
        'payloadComparison': measurements}, ensure_ascii=False), flush=True)
    if not all(quality.values()):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
