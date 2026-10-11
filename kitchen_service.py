"""Authoritative household commands, independent of HTTP and database adapters.

The browser's KitchenCore remains the guest-mode implementation. Authenticated
clients submit intentions; this module alone calculates shared inventory.
"""
import copy
import json
import re
import base64
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


class KitchenError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def uid():
    return str(uuid.uuid4())


def number(value, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise KitchenError('请输入有效数量')
    try:
        n = Decimal(str(value))
        if not n.is_finite() or n < 0 or n > 1_000_000_000 or positive and n <= 0:
            raise KitchenError('请输入有效的正数量' if positive else '数量不正确')
        n = n.quantize(Decimal('.0001'), rounding=ROUND_HALF_UP)
        if positive and not n:
            raise KitchenError('数量太小，请至少填写0.0001')
        return float(n)
    except InvalidOperation:
        raise KitchenError('数量不正确')


def text(value, label='名字', limit=100):
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > limit:
        raise KitchenError(f'请填写{limit}字以内的{label}')
    return value.strip()


def food_name(value):
    name = text(value, '食材名字')
    return {'西红柿': '番茄', '马铃薯': '土豆'}.get(name, name)


def amount(value, unit):
    unit = text(unit, '单位', 20)
    canonical, factor = {'g': ('克', 1), 'kg': ('克', 1000), '千克': ('克', 1000),
                         'ml': ('毫升', 1), '升': ('毫升', 1000),
                         '颗': ('个', 1), '枚': ('个', 1)}.get(unit, (unit, 1))
    return number(str(Decimal(str(value))*factor)), canonical


def find(rows, identity, label):
    row = next((r for r in rows if r['id'] == identity), None)
    if row is None:
        raise KitchenError('找不到' + label, 404)
    return row


def active(state):
    return [op for op in state['operations'] if op['status'] == 'active']


def reserved(state, stock_id, except_id=None):
    return number(sum(a['quantity'] for op in active(state) if op['id'] != except_id
                      for a in op['allocations'] if a['stockId'] == stock_id))


def available(state, stock):
    return number(stock['quantity'] - reserved(state, stock['id']))


def remaining(state, need):
    if need['required'] is None:
        return None
    allocated = sum(a['quantity'] for op in active(state)
                    if op['mealId'] == state['meal']['id'] and op['needId'] == need['id']
                    for a in op['allocations'])
    return number(max(0, need['required'] - allocated))


def ready(state, need):
    return bool(need.get('declared') or remaining(state, need) == 0 and not need['unknown'])


def needs_for(dishes):
    needs = {}
    for dish in dishes:
        for ingredient in dish['ingredients']:
            name = food_name(ingredient['name'])
            unit = ingredient.get('unit', '')
            quantity = ingredient.get('quantity')
            known = isinstance(quantity, (int, float)) and not isinstance(quantity, bool) and bool(unit) and not ingredient.get('pending')
            q, canonical = amount(str(Decimal(str(quantity))*Decimal(str(dish['targetServings']))/Decimal(str(dish['servings']))), unit) if known else (0, unit)
            key = json.dumps([name, canonical], ensure_ascii=False, separators=(',', ':'))
            if key not in needs:
                needs[key] = {'id': key, 'name': name, 'unit': canonical, 'required': None,
                              'unknown': 0, 'recipes': [], 'declared': False}
                if ingredient.get('iconId'):
                    needs[key]['iconId'] = ingredient['iconId']
            need = needs[key]
            if known:
                need['required'] = number((need['required'] or 0) + q)
            else:
                need['unknown'] += 1
            if dish['name'] not in need['recipes']:
                need['recipes'].append(dish['name'])
    return list(needs.values())


def image(value, limit=2_000_000):
    if value is None or value == '':
        return None
    if isinstance(value,str) and re.fullmatch(r'/api/files/[a-f0-9]{32}',value):
        return value
    if not isinstance(value, str) or len(value) > limit or not re.fullmatch(r'data:image/(jpeg|png|webp);base64,[A-Za-z0-9+/]+=*', value):
        raise KitchenError('请选择有效且大小合适的图片')
    try:
        raw = base64.b64decode(value.split(',', 1)[1], validate=True)
    except ValueError:
        raise KitchenError('图片格式不正确')
    if not (raw.startswith(b'\xff\xd8\xff') or raw.startswith(b'\x89PNG\r\n\x1a\n') or raw.startswith(b'RIFF') and raw[8:12] == b'WEBP'):
        raise KitchenError('图片格式不正确')
    return value


def recipe(value):
    if not isinstance(value, dict):
        raise KitchenError('菜谱格式不正确')
    card = copy.deepcopy(value)
    card['id'] = text(card.get('id'), '菜谱编号', 120)
    card['name'] = text(card.get('name'), '菜名')
    card['servings'] = number(card.get('servings', 1), True)
    if not isinstance(card.get('ingredients'), list) or not card['ingredients'] or len(card['ingredients']) > 200:
        raise KitchenError('请添加1到200种食材')
    for row in card['ingredients']:
        if not isinstance(row, dict):
            raise KitchenError('食材格式不正确')
        row['name'] = text(row.get('name'), '食材名字')
        unit = row.get('unit', '')
        if not isinstance(unit, str) or len(unit) > 20:
            raise KitchenError('食材单位不正确')
        if row.get('quantity') is not None:
            row['quantity'] = number(row['quantity'])
    if not isinstance(card.get('steps'), list) or not card['steps'] or len(card['steps']) > 200:
        raise KitchenError('请填写制作步骤')
    card['steps'] = [text(step, '制作步骤', 10000) for step in card['steps']]
    if 'coverImage' in card:
        card['coverImage'] = image(card['coverImage'])
    refs = card.get('evidenceIds', [])
    if not isinstance(refs, list) or any(not isinstance(ref, str) for ref in refs):
        raise KitchenError('来源证据编号不正确')
    card['evidenceIds'] = refs
    return card


def validate_bundle(bundle):
    """Check imported/restored data too: migration cannot invent consumed stock."""
    state = bundle['state']
    for key in ('spaces', 'stocks', 'operations', 'records'):
        rows = state[key]
        if any(not isinstance(row, dict) or not isinstance(row.get('id'), str) for row in rows) or len({r['id'] for r in rows}) != len(rows):
            raise KitchenError('家庭记录编号重复或无效')
    cards = bundle['recipeData']['recipes']
    if any(not isinstance(card, dict) for card in cards):
        raise KitchenError('菜谱格式不正确')
    evidence = bundle['recipeData'].get('evidence', {})
    if not isinstance(evidence, dict) or any(not isinstance(row, dict) or row.get('id') != identity or not isinstance(row.get('kind'), str) or not isinstance(row.get('text'), str) for identity, row in evidence.items()):
        raise KitchenError('来源证据格式不正确')
    if len({card.get('id') for card in cards}) != len(cards):
        raise KitchenError('菜谱编号重复')
    for card in cards:
        checked = recipe(card)
        if any(identity not in evidence for identity in checked['evidenceIds']):
            raise KitchenError('菜谱缺少来源证据')
    stocks = {s['id']: s for s in state['stocks']}
    needs = {n['id']: n for n in state['meal']['needs']}
    if len(needs) != len(state['meal']['needs']):
        raise KitchenError('食材需求编号重复')
    meal = state['meal']
    if meal['status'] in ('locked', 'cooking', 'done'):
        if not meal['dishes']:
            raise KitchenError('已确认餐次缺少菜谱快照')
        for dish in meal['dishes']:
            recipe(dish)
            number(dish.get('targetServings'), True)
        if needs_for(meal['dishes']) != [{**n, 'declared': False} for n in meal['needs']]:
            raise KitchenError('食材需求与已确认菜单不一致')
    if meal['status'] == 'done' and not any(r.get('mealId') == meal['id'] for r in state['records']):
        raise KitchenError('已完成餐次缺少做饭记录')
    for selection in meal['selections']:
        if not isinstance(selection, dict):
            raise KitchenError('菜谱选择不正确')
        number(selection.get('servings'), True)
        if meal['status'] == 'draft':
            find(cards, selection.get('recipeId'), '已选菜谱')
    for stock in stocks.values():
        number(stock['quantity'])
    for op in state['operations']:
        if op.get('status') not in ('active', 'undone', 'released', 'consumed') or op.get('type') not in ('left', 'right'):
            raise KitchenError('准备记录状态不正确')
        number(op.get('quantity'), True)
        if not isinstance(op.get('allocations'), list):
            raise KitchenError('准备记录格式不正确')
        for row in op['allocations']:
            if not isinstance(row, dict):
                raise KitchenError('准备记录格式不正确')
            number(row.get('quantity'), True)
            if row.get('stockId') not in stocks:
                raise KitchenError('准备记录对应的库存不存在')
        if op['status'] == 'active':
            if op.get('mealId') != state['meal']['id'] or state['meal']['status'] not in ('locked', 'cooking') or op.get('needId') not in needs:
                raise KitchenError('预留记录对应的餐次或需求不正确')
            need = needs[op['needId']]
            if sum(a['quantity'] for a in op['allocations']) > op['quantity'] + .00001:
                raise KitchenError('准备分配量不能超过记录量')
            for allocation in op['allocations']:
                stock = stocks[allocation['stockId']]
                if food_name(stock['name']) != need['name'] or stock['unit'] != need['unit']:
                    raise KitchenError('预留食材或单位与需求不一致')
    for stock in stocks.values():
        available(state, stock)
    for need in needs.values():
        if need['required'] is not None:
            number(need['required'])
            allocated = sum(a['quantity'] for op in active(state) if op['needId'] == need['id'] for a in op['allocations'])
            if allocated > need['required'] + .00001:
                raise KitchenError('预留不能超过本餐需求')


def apply(bundle, kind, payload, role, meal_id):
    """Mutate an isolated bundle. Caller persists atomically with command receipt."""
    state, recipes = bundle['state'], bundle['recipeData']['recipes']
    meal = state['meal']
    if role not in ('chef', 'foodie'):
        raise KitchenError('请选择有效角色')
    if kind.startswith('meal.') and meal_id != meal['id']:
        raise KitchenError('当前餐次已变化，请刷新后重试', 409)
    if role != 'chef' and kind not in ('meal.pick', 'meal.select', 'meal.servings', 'record.photo'):
        raise KitchenError('请切换到主厨来操作', 403)

    def phase(expected):
        if meal['status'] != expected:
            raise KitchenError('本餐菜单已固定，暂无法点菜' if expected == 'draft' else '餐次状态已变化，请刷新后重试', 409)

    if kind in ('meal.pick', 'meal.select', 'meal.servings'):
        phase('draft')
        if kind == 'meal.servings':
            row = next((r for r in meal['selections'] if r['recipeId'] == payload.get('recipeId')), None)
            if not row:
                raise KitchenError('先选这道菜')
            row['servings'] = number(payload.get('servings'), True)
        else:
            ids = payload.get('recipeIds') if kind == 'meal.select' else [payload.get('recipeId')]
            if not isinstance(ids, list) or not ids or len(ids) > 100 or any(not isinstance(i, str) for i in ids):
                raise KitchenError('菜谱选择不正确')
            selected = payload.get('selected', True)
            if type(selected) is not bool:
                raise KitchenError('菜谱选择不正确')
            for identity in ids:
                card = find(recipes, identity, '这道菜')
                old = next((r for r in meal['selections'] if r['recipeId'] == identity), None)
                if selected and not old:
                    meal['selections'].append({'recipeId': identity, 'servings': card['servings']})
                elif not selected and old:
                    meal['selections'].remove(old)
    elif kind == 'meal.lock':
        phase('draft')
        if not meal['selections']:
            raise KitchenError('先选一道想吃的菜')
        meal['dishes'] = [{**copy.deepcopy(find(recipes, r['recipeId'], '已选菜谱')), 'targetServings': r['servings']} for r in meal['selections']]
        meal['needs'] = needs_for(meal['dishes'])
        meal['status'] = 'locked'
    elif kind == 'meal.prepare':
        phase('locked')
        need = find(meal['needs'], payload.get('needId'), '这项食材')
        if ready(state, need):
            raise KitchenError('这项已经准备好了', 409)
        direction = payload.get('direction')
        if direction not in ('left', 'right'):
            raise KitchenError('准备方式无效')
        q = number(payload.get('quantity'), True)
        q, unit = amount(q, (payload.get('unit') or need['unit'] or '克') if direction == 'right' else need['unit'] or '克')
        rest = remaining(state, need)
        if rest is not None and unit != need['unit']:
            raise KitchenError('请使用与需求相同的单位')
        matches = [s for s in state['stocks'] if food_name(s['name']) == need['name'] and s['unit'] == unit]
        op = {'id': uid(), 'mealId': meal['id'], 'needId': need['id'], 'type': direction,
              'quantity': q, 'status': 'active', 'allocations': [], 'stockId': None}
        if direction == 'left':
            if rest is None:
                raise KitchenError('用量未写明，可以先标记已备好，不自动扣库存')
            if q > rest + .00001:
                raise KitchenError('使用量不能超过本餐还差的数量')
            stock_ids = payload.get('stockIds')
            if stock_ids is not None:
                if not isinstance(stock_ids, list) or any(not isinstance(i, str) for i in stock_ids) or len(set(stock_ids)) != len(stock_ids) or any(i not in [s['id'] for s in matches] for i in stock_ids):
                    raise KitchenError('请选择对应的库存位置')
                matches = [find(matches, i, '这份食材') for i in stock_ids]
            if q > sum(available(state, s) for s in matches) + .00001:
                raise KitchenError('家里已记录的可用量不够，可以补录')
            left = q
            for stock in matches:
                take = min(left, available(state, stock))
                if take:
                    op['allocations'].append({'stockId': stock['id'], 'quantity': take})
                left = number(max(0, left - take))
                if not left:
                    break
        else:
            stock = matches[0] if matches else {'id': uid(), 'name': need['name'], 'quantity': 0,
                                              'unit': unit, 'space': None, 'zone': 0}
            if not matches:
                if need.get('iconId'):
                    stock['iconId'] = need['iconId']
                state['stocks'].append(stock)
            stock['quantity'] = number(stock['quantity'] + q)
            op['stockId'] = stock['id']
            take = min(q, rest) if rest is not None else 0
            if take:
                op['allocations'].append({'stockId': stock['id'], 'quantity': take})
        state['operations'].append(op)
        return op
    elif kind == 'meal.declare':
        phase('locked')
        need = find(meal['needs'], payload.get('needId'), '这项食材')
        if not need['unknown']:
            raise KitchenError('请按明确数量准备这项食材')
        need['declared'] = True
    elif kind == 'meal.undo':
        phase('locked')
        op = find(state['operations'], payload.get('operationId'), '这次准备记录')
        if op['status'] != 'active' or op['mealId'] != meal['id']:
            raise KitchenError('这次操作已经处理过了', 409)
        if op['type'] == 'right':
            stock = find(state['stocks'], op['stockId'], '这份食材')
            if stock['quantity'] - op['quantity'] + .00001 < reserved(state, stock['id'], op['id']):
                raise KitchenError('这份食材已被后续操作使用，暂时不能撤销')
            stock['quantity'] = number(stock['quantity'] - op['quantity'])
        op['status'] = 'undone'
    elif kind == 'meal.begin':
        phase('locked')
        meal['status'] = 'cooking'
    elif kind == 'meal.finish':
        if meal['status'] == 'done':
            return next(r for r in state['records'] if r['mealId'] == meal['id'])
        phase('cooking')
        operations = [op for op in active(state) if op['mealId'] == meal['id']]
        for stock in state['stocks']:
            stock['quantity'] = number(stock['quantity'] - sum(a['quantity'] for op in operations for a in op['allocations'] if a['stockId'] == stock['id']))
        record = {'id': uid(), 'mealId': meal['id'], 'at': datetime.now(timezone.utc).isoformat(),
                  'dishes': copy.deepcopy(meal['dishes']), 'unrecorded': [n['name'] for n in meal['needs'] if not ready(state, n)], 'photo': None}
        for op in operations:
            op['status'] = 'consumed'
        meal['status'] = 'done'
        state['records'].insert(0, record)
        return record
    elif kind == 'meal.cancel':
        if meal['status'] not in ('draft', 'locked', 'cooking'):
            raise KitchenError('这餐已经结束', 409)
        for op in active(state):
            if op['mealId'] == meal['id']:
                op['status'] = 'released'
        meal['status'] = 'cancelled'
    elif kind == 'meal.new':
        if meal['status'] not in ('done', 'cancelled'):
            raise KitchenError('先完成或取消当前这餐', 409)
        state['meal'] = {'id': uid(), 'status': 'draft', 'selections': [], 'dishes': [], 'needs': []}
    elif kind in ('stock.add', 'stock.reduce', 'stock.move'):
        if kind == 'stock.add':
            name = text(payload.get('name'), '食材名字')
            q, unit = amount(number(payload.get('quantity'), True), payload.get('unit') or '克')
            space, zone = position(state, payload)
            stock = next((s for s in state['stocks'] if (s['name'], s['unit'], s['space'], s['zone']) == (name, unit, space, zone)), None)
            if stock is None:
                stock = {'id': uid(), 'name': name, 'unit': unit, 'quantity': 0, 'space': space, 'zone': zone}
                state['stocks'].append(stock)
            stock['quantity'] = number(stock['quantity'] + q)
            if payload.get('iconId'):
                stock['iconId'] = text(payload['iconId'], '图标编号', 120)
        else:
            stock = find(state['stocks'], payload.get('stockId'), '这份食材')
            if kind == 'stock.move':
                stock['space'], stock['zone'] = position(state, payload)
            else:
                q = number(payload.get('quantity'), True)
                if q > available(state, stock) + .00001:
                    raise KitchenError('不能减少超过可用量的食材，请先撤销本餐预留')
                stock['quantity'] = number(stock['quantity'] - q)
        return stock
    elif kind in ('space.create', 'space.update', 'space.delete'):
        if kind == 'space.delete':
            space = find(state['spaces'], payload.get('spaceId'), '这个储物空间')
            for stock in state['stocks']:
                if stock['space'] == space['id']:
                    stock['space'], stock['zone'] = None, 0
            state['spaces'].remove(space)
        else:
            layout = payload.get('layout')
            if not isinstance(layout, str):
                raise KitchenError('请选择有效布局')
            defaults = {'four': ['左上', '右上', '左下', '右下'], 'two': ['上层', '下层'], 'horizontal': ['左侧', '右侧']}.get(layout)
            names = payload.get('zones')
            if not defaults or not isinstance(names, list) or len(names) != len(defaults):
                raise KitchenError('请选择有效布局并填写对应分区')
            zones = [text(name or defaults[i], '分区名字', 30) for i, name in enumerate(names)]
            name = text(payload.get('name'), '空间名字', 30)
            if kind == 'space.create':
                if payload.get('type') not in ('fridge', 'cupboard'):
                    raise KitchenError('请选择空间类型')
                space = {'id': uid(), 'type': payload['type']}
                state['spaces'].append(space)
            else:
                space = find(state['spaces'], payload.get('spaceId'), '这个储物空间')
            space.update(name=name, layout=layout, zones=zones)
            for stock in state['stocks']:
                if stock['space'] == space['id']:
                    stock['zone'] = min(stock['zone'], len(zones)-1)
            return space
    elif kind == 'recipe.upsert':
        card = recipe(payload.get('recipe'))
        evidence = bundle['recipeData'].setdefault('evidence', {})
        incoming = payload.get('evidence', {})
        if not isinstance(incoming, dict):
            raise KitchenError('来源证据格式不正确')
        for identity, row in incoming.items():
            if not isinstance(row, dict) or row.get('id') != identity or not isinstance(row.get('kind'), str) or not isinstance(row.get('text'), str):
                raise KitchenError('来源证据格式不正确')
            if identity in evidence and evidence[identity] != row:
                raise KitchenError('来源证据编号冲突')
            evidence[identity] = row
        if any(identity not in evidence for identity in card['evidenceIds']):
            raise KitchenError('菜谱缺少来源证据')
        old = next((r for r in recipes if r['id'] == card['id']), None)
        if old is not None:
            recipes[recipes.index(old)] = card
        else:
            recipes.insert(0, card)
        return card
    elif kind == 'record.photo':
        record = find(state['records'], payload.get('recordId'), '本餐记录')
        record['photo'] = image(payload.get('photo'), 3_000_000)
        return record
    else:
        raise KitchenError('不支持的家庭操作')
    return None


def position(state, payload):
    identity, zone = payload.get('space'), payload.get('zone', 0)
    if identity is None:
        return None, 0
    space = find(state['spaces'], identity, '这个储物空间')
    if type(zone) is not int or zone < 0 or zone >= len(space['zones']):
        raise KitchenError('请选择有效的储物位置')
    return identity, zone
