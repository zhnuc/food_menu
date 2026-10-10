/* Shared evidence storage and legacy backup migration; no UI dependency. */
(() => {
  const uuid=typeof module!=='undefined' ? require('./ids.js').uuid : RecipeIds.uuid;
  function createStore(input = []) {
    const evidence = Object.create(null);
    const byContent = new Map();
    const aliases = new Map();
    const identity = row => JSON.stringify(Object.fromEntries(
      Object.entries(row).filter(([key]) => key !== 'id').sort(([a], [b]) => a.localeCompare(b))));

    function register(rows = []) {
      return rows.map(row => {
        if (!row || typeof row.kind !== 'string' || typeof row.text !== 'string') {
          throw Error('来源证据格式不正确');
        }
        const key = identity(row);
        const oldId = aliases.get(row.id) || row.id;
        if (evidence[oldId] && identity(evidence[oldId]) !== key) throw Error('来源证据编号冲突');
        if (byContent.has(key)) {
          const existing = byContent.get(key);
          if (row.id) aliases.set(row.id, existing);
          return existing;
        }
        const id = row.id || 'ev-' + uuid();
        if (evidence[id] && identity(evidence[id]) !== key) throw Error('来源证据编号冲突');
        evidence[id] = {...row, id};
        byContent.set(key, id);
        return id;
      });
    }

    function resolve(recipe) {
      return (recipe.evidenceIds || []).map(id => {
        if (!evidence[id]) throw Error('备份缺少对应的来源证据');
        return evidence[id];
      });
    }

    function normalize(recipe, fallback = []) {
      if (!recipe || typeof recipe.name !== 'string' || !Array.isArray(recipe.ingredients) ||
          !recipe.ingredients.every(i => typeof i.name === 'string') || !Array.isArray(recipe.steps) ||
          !recipe.steps.every(s => typeof s === 'string') || !Number.isFinite(recipe.servings) || recipe.servings <= 0) {
        throw Error('菜谱格式不正确');
      }
      const {evidence: legacy, ...card} = recipe;
      card.evidenceIds = legacy ? register(legacy) : (card.evidenceIds || register(fallback));
      card.evidenceIds = card.evidenceIds.map(id => aliases.get(id) || id);
      resolve(card);
      return card;
    }

    function snapshot(recipes) {
      const used = new Set(recipes.flatMap(r => r.evidenceIds || []));
      return {version: 2, recipes, evidence: Object.fromEntries([...used].map(id => [id, evidence[id]]))};
    }

    const raw = Array.isArray(input) ? input : input?.version === 2 && Array.isArray(input.recipes) ? input.recipes : null;
    if (!raw) throw Error('备份格式不正确');
    // Re-map references after content deduplication, including imported v2 files.
    const mapping = new Map();
    if (!Array.isArray(input)) {
      for (const [oldId, row] of Object.entries(input.evidence || {})) mapping.set(oldId, register([row])[0]);
    }
    const recipes = raw.map(row => normalize({...row, ...(row.evidenceIds ?
      {evidenceIds: row.evidenceIds.map(id => mapping.get(id) || id)} : {})}));
    return {recipes, evidence, register, resolve, normalize, snapshot};
  }
  const api = {createStore};
  if (typeof module !== 'undefined') module.exports = api;
  else globalThis.RecipeData = api;
})();
