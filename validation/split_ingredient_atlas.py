"""Split the approved generated atlas into reusable transparent app assets.

Run from the repository root with .venv/Scripts/python.exe.
The plan records inspected gutter cuts, rather than assuming the model drew an
exact grid. Source pixels are retained; only near-invisible alpha noise is removed.
"""
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / 'output/imagegen/ingredient-icons-v1'
DEST = ROOT / 'web/assets/ingredients/v1'


def main():
    plan_path = ROOT / 'validation/ingredient-atlas-plan.json'
    plan = json.loads(plan_path.read_text(encoding='utf-8'))
    source_path = SOURCE_DIR / 'atlas-source.png'
    source = Image.open(source_path)
    if source.mode != 'RGBA':
        raise ValueError('Source must already have a genuine alpha channel')
    xs, ys = plan['xCuts'], plan['yCuts']
    assert source.size == (xs[-1], ys[-1]), 'Update inspected cuts for the new source'
    assert len(plan['icons']) == plan['columns'] * plan['rows'] == 30
    assert len({item['id'] for item in plan['icons']}) == 30
    for size in (128, 256):
        (DEST / str(size)).mkdir(parents=True, exist_ok=True)
    (SOURCE_DIR / 'native-crops').mkdir(exist_ok=True)
    atlas = Image.new('RGBA', (256 * plan['columns'], 256 * plan['rows']))
    preview = Image.new('RGB', (180 * plan['columns'], 184 * plan['rows']), '#f5f7ef')
    draw = ImageDraw.Draw(preview)
    font = ImageFont.truetype('C:/Windows/Fonts/msyh.ttc', 17)
    records = []
    for item in plan['icons']:
        col, row = item['column'], item['row']
        box = (xs[col], ys[row], xs[col + 1], ys[row + 1])
        cell = source.crop(box)
        alpha = cell.getchannel('A')
        body = alpha.point(lambda value: 255 if value > 128 else 0).getbbox()
        if not body:
            raise ValueError(f"Empty cell: {item['id']}")
        gaps = [body[0], body[1], cell.width - body[2], cell.height - body[3]]
        if min(gaps) <= 0:
            raise ValueError(f"Icon touches crop boundary: {item['id']}, {gaps}")
        # Keep antialiased edges and ignore alpha 1-8 background speckles.
        alpha = alpha.point(lambda value: 0 if value <= 8 else value)
        cell.putalpha(alpha)
        trim = (max(0, body[0] - 4), max(0, body[1] - 4),
                min(cell.width, body[2] + 4), min(cell.height, body[3] + 4))
        native = cell.crop(trim)
        native.save(SOURCE_DIR / 'native-crops' / (item['id'] + '.png'), optimize=True)
        for size in (128, 256):
            content = native.copy()
            max_extent = round(size * .82)
            ratio = max_extent / max(content.size)
            content = content.resize((round(content.width * ratio), round(content.height * ratio)), Image.Resampling.LANCZOS)
            # Transparent RGB is zeroed to avoid colored halos in renderers.
            transparent = content.getchannel('A').point(lambda v: 255 if v == 0 else 0)
            content.paste((0, 0, 0, 0), (0, 0), transparent)
            canvas = Image.new('RGBA', (size, size))
            canvas.alpha_composite(content, ((size - content.width) // 2, (size - content.height) // 2))
            canvas.save(DEST / str(size) / (item['id'] + '.png'), optimize=True)
            assert canvas.getpixel((0, 0))[3] == 0
            assert canvas.getchannel('A').getbbox() is not None
            if size == 256:
                atlas.alpha_composite(canvas, (col * size, row * size))
                thumb = canvas.resize((140, 140), Image.Resampling.LANCZOS)
                preview.paste(thumb, (col * 180 + 20, row * 184 + 3), thumb)
        draw.text((col * 180 + 90, row * 184 + 158), item['name'], fill='#334f39', font=font, anchor='mm')
        records.append({
            'id': item['id'], 'name': item['name'], 'category': item['category'],
            'aliases': item['aliases'], 'row': row, 'column': col,
            'files': {str(size): f"{size}/{item['id']}.png" for size in (128, 256)},
            'sourceCell': list(box), 'nativeSize': list(native.size),
            'spriteRect': [col * 256, row * 256, 256, 256],
        })
    atlas.save(DEST / 'atlas.png', optimize=True)
    preview.save(SOURCE_DIR / 'preview.png', optimize=True)
    manifest = {
        'version': 1, 'style': 'A 清爽扁平', 'count': len(records),
        'canvasSizes': [128, 256], 'sourceSize': list(source.size),
        'sourceSha256': hashlib.sha256(source_path.read_bytes()).hexdigest(),
        'atlas': {'file': 'atlas.png', 'size': list(atlas.size), 'columns': 6, 'rows': 5},
        'icons': records,
    }
    (DEST / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    names = {name: item['id'] for item in records for name in [item['name'], *item['aliases']]}
    resolver = '''/* Generated from ingredient-atlas-plan.json. Visual aliases only. */
(() => {
  const names = NAMES;
  const items = ITEMS;
  const categories = ['vegetable', 'meat', 'aquatic', 'staple', 'seasoning', 'other'];
  window.IngredientIcons = Object.freeze({
    items,
    id(name) { const key=String(name ?? '').trim();return Object.hasOwn(names,key)?names[key]:'category-other'; },
    valid(id) { return items.some(item => item.id === id); },
    url(name, category = 'other', selectedId) {
      const fallback = categories.includes(category) ? category : 'other';
      const key=String(name ?? '').trim();
      const id = items.some(item => item.id === selectedId) ? selectedId : Object.hasOwn(names,key) ? names[key] : 'category-' + fallback;
      return '/assets/ingredients/v1/128/' + id + '.png';
    }
  });
})();
'''.replace('NAMES', json.dumps(names, ensure_ascii=False, separators=(',', ':'))).replace('ITEMS', json.dumps([{'id': item['id'], 'name': item['name'], 'category': item['category']} for item in records], ensure_ascii=False, separators=(',', ':')))
    (ROOT / 'web/ingredient-icons.js').write_text(resolver, encoding='utf-8')
    with ZipFile(SOURCE_DIR / 'ingredient-icons-v1.zip', 'w', ZIP_DEFLATED) as package:
        for path in sorted(DEST.rglob('*')):
            if path.is_file():
                package.write(path, 'ingredients-v1/' + path.relative_to(DEST).as_posix())
        for filename in ('atlas-source.png', 'preview.png', 'prompt.txt', 'README.md'):
            package.write(SOURCE_DIR / filename, filename)
        package.write(plan_path, 'ingredient-atlas-plan.json')
        package.write(Path(__file__), 'split_ingredient_atlas.py')
        package.write(ROOT / 'web/ingredient-icons.js', 'ingredient-icons.js')
    print(json.dumps({'count': len(records), 'pngFiles': 60, 'alpha': 'verified',
                      'source': source.size, 'atlas': atlas.size,
                      'assetsKB': round(sum(p.stat().st_size for p in DEST.rglob('*.png')) / 1024)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
