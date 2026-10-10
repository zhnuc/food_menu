"""Live end-to-end recipe parsing; archive sanitized evidence and results."""
import argparse
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import server
sys.stdout.reconfigure(encoding='utf-8')

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('url')
    parser.add_argument('output')
    args=parser.parse_args()
    print('开始实际解析：'+args.url,flush=True)
    data=server.parse({'share':args.url})
    path=ROOT/'validation'/args.output
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'recipes':[r['name'] for r in data.get('recipes',[])],
        'media':data.get('media',{}),'evidenceCount':len(data.get('evidence',[])),
        'warnings':data.get('warnings',[])},ensure_ascii=False),flush=True)
