"""Shared source, evidence and recipe contracts; no runtime dependencies."""
from dataclasses import dataclass, field
import hashlib
import json
from typing import TypedDict


class Evidence(TypedDict, total=False):
    id: str
    kind: str
    text: str
    locator: str
    asset: str
    dish: str
    standalone: bool


class Ingredient(TypedDict, total=False):
    name: str
    quantity: float | None
    unit: str
    evidence: str
    pending: bool
    note: str


class Recipe(TypedDict, total=False):
    id: str
    name: str
    servings: float
    targetServings: float
    source: str
    ingredients: list[Ingredient]
    steps: list[str]
    evidenceIds: list[str]
    selected: bool


class ParseResult(TypedDict):
    schemaVersion: int
    recipes: list[Recipe]
    evidence: list[Evidence]
    media: dict
    warnings: list[str]
    timings: dict


@dataclass
class SourcePost:
    context: dict
    media: dict = field(default_factory=dict)
    evidence: list[Evidence] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    timings: dict = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, url: str, data: dict):
        rows = data.get('evidence', [])
        if not isinstance(rows, list) or any(not isinstance(row, dict) or
                not isinstance(row.get('kind'), str) or not isinstance(row.get('text'), str) for row in rows):
            raise ValueError('来源证据格式无效')
        context = {'url': url, **{key: data[key] for key in
            ('platform', 'title', 'author', 'description', 'canonicalSource') if data.get(key)}}
        context.setdefault('description', '\n'.join(row['text'] for row in rows if row['kind'] == 'article'))
        media = {key: data[key] for key in ('platform', 'title', 'author', 'duration',
            'video', 'images', 'frames', 'canonicalSource') if key in data}
        return cls(context, media, rows, list(data.get('warnings', [])), dict(data.get('_timings', {})))


def evidence_id(row: Evidence) -> str:
    content = {key: value for key, value in row.items() if key != 'id'}
    digest = hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return 'ev-' + digest[:24]


def shared_evidence(rows: list[Evidence]) -> list[Evidence]:
    unique = {}
    for row in rows:
        identifier = evidence_id(row)
        unique.setdefault(identifier, {**row, 'id': identifier})
    return list(unique.values())
