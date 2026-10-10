"""One-time mechanical move of existing responsibilities, preserving behavior."""
import ast
from pathlib import Path

root = Path(__file__).resolve().parents[1]
source = (root/'server.py').read_text(encoding='utf-8')
lines = source.splitlines(keepends=True)
nodes = {node.name: node for node in ast.parse(source).body if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
if '_parse' not in nodes:
    raise SystemExit('Backend is already split; nothing to migrate.')
def section(name):
    node = nodes[name]
    return ''.join(lines[node.lineno-1:node.end_lineno])+'\n\n'

(root/'sources.py').write_text('"""Platform routing and short-link expansion."""\nimport re\nfrom urllib.parse import urlparse\nfrom urllib.request import Request, HTTPRedirectHandler, build_opener\nimport ai\nfrom ai import request_json\nimport local_media\nimport video_media\n\n'+''.join(section(name) for name in ('source_url','BiliRedirect','expand_bili','extract_source')),encoding='utf-8')

constants=source[source.index('ALIASES='):source.index('def _chinese_amount')]
prompt_nodes=[node for node in ast.walk(nodes['_parse']) if isinstance(node,(ast.Assign,ast.AugAssign)) and isinstance(getattr(node,'value',None),ast.Constant) and isinstance(node.value.value,str) and ((isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='prompt' for t in node.targets)) or (isinstance(node,ast.AugAssign) and isinstance(node.target,ast.Name) and node.target.id=='prompt'))]
prompt=''.join(node.value.value for node in sorted(prompt_nodes,key=lambda n:n.lineno))
(root/'recipes.py').write_text('"""Recipe evidence validation and shopping quantities."""\nimport math\nimport re\nfrom contracts import Evidence, Recipe\n\nPROMPT = '+repr(prompt)+'\n\n'+constants+''.join(section(name) for name in ('_chinese_amount','_quantity_supported','shopping','validate_recipes')),encoding='utf-8')

local=(root/'local_media.py').read_text(encoding='utf-8')
start=local.index('def enrich_visuals(')
(root/'vision.py').write_text('"""Shared batched photo/frame recognition, independent of source platform."""\nimport hashlib\nimport json\nimport math\nimport os\nimport time\nfrom concurrent.futures import ThreadPoolExecutor\nfrom ai import response_json\nfrom visual_pack import contact_sheet\n\n'+local[start:],encoding='utf-8')
local=local[:start].replace('from ai import response_json\nfrom visual_pack import contact_sheet\n','from vision import enrich_visuals\n').replace('import hashlib, json, re, os, time, math','import hashlib, json, re, os, time')
(root/'local_media.py').write_text(local,encoding='utf-8')
video=(root/'video_media.py').read_text(encoding='utf-8').replace('import local_media','import vision').replace('local_media.enrich_visuals','vision.enrich_visuals')
(root/'video_media.py').write_text(video,encoding='utf-8')

handler=section('Handler')
(root/'server.py').write_text('"""HTTP transport and static assets; business flow lives in pipeline.py."""\nimport json\nimport mimetypes\nimport os\nimport re\nfrom pathlib import Path\nfrom http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler\nimport ai\nfrom pipeline import parse\nfrom recipes import shopping\n\nROOT = Path(__file__).parent\n\n'+handler+source[source.index("if __name__=='__main__':"):],encoding='utf-8')

# Update internal test/benchmark patch points to the module that now owns them.
replacements={'server.request_json':'pipeline.request_json','server.RECIPE_CACHE':'pipeline.RECIPE_CACHE',
 'server.extract_source':'pipeline.extract_source','server.source_url':'sources.source_url',
 'server.expand_bili':'sources.expand_bili','server.build_opener':'sources.build_opener',
 'server.validate_recipes':'recipes_domain.validate_recipes','server.local_media':'sources.local_media',
 'server.video_media':'sources.video_media','video_media.local_media.enrich_visuals':'video_media.vision.enrich_visuals',
 'local_media.enrich_visuals':'vision.enrich_visuals'}
for directory in ('tests','validation'):
    for path in (root/directory).glob('*.py'):
        if path.name=='split_backend.py':continue
        text=path.read_text(encoding='utf-8')
        if not any(old in text for old in replacements):continue
        for old,new in replacements.items():text=text.replace(old,new)
        anchor='import server\n'
        imports='import pipeline\nimport sources\nimport recipes as recipes_domain\nimport vision\n'
        if anchor in text:text=text.replace(anchor,anchor+imports,1)
        else:text=imports+text
        path.write_text(text,encoding='utf-8')
