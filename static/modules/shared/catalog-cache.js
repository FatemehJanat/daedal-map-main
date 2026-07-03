import { readSharedCache, writeSharedCache } from './shared-cache.js';

export const PUBLIC_PACK_CATALOG_CACHE_KEY = 'daedalmap-public-pack-catalog-v1';
export const PUBLIC_PACK_CATALOG_TTL_MS = 15 * 60 * 1000;
export const PUBLIC_PACK_CATALOG_API = '/api/catalog/packs?format=json';

function hasUsablePackArray(value) {
  return Array.isArray(value?.packs);
}

export async function readPublicPackCatalogCache() {
  const entry = await readSharedCache(PUBLIC_PACK_CATALOG_CACHE_KEY);
  const value = entry?.value ?? entry;
  if (!hasUsablePackArray(value)) return null;
  return value;
}

export async function writePublicPackCatalogCache(packs) {
  const value = {
    savedAt: Date.now(),
    packs: Array.isArray(packs) ? packs : []
  };
  await writeSharedCache(PUBLIC_PACK_CATALOG_CACHE_KEY, value, PUBLIC_PACK_CATALOG_TTL_MS);
  return value;
}

export async function loadPublicPackCatalog({
  forceRefresh = false,
  endpoint = PUBLIC_PACK_CATALOG_API,
  fetchImpl = fetch
} = {}) {
  if (!forceRefresh) {
    const cached = await readPublicPackCatalogCache();
    if (cached?.packs?.length) {
      return {
        packs: cached.packs,
        cached: true,
        source: 'shared-cache'
      };
    }
  }

  const response = await fetchImpl(endpoint, {
    headers: { Accept: 'application/json' }
  });
  if (!response.ok) {
    throw new Error(`Public pack catalog request failed: HTTP ${response.status}`);
  }

  const payload = await response.json();
  const packs = Array.isArray(payload?.packs) ? payload.packs : [];
  await writePublicPackCatalogCache(packs);
  return {
    packs,
    cached: false,
    source: 'network'
  };
}

export async function findPublicPackCatalogEntry(packId, options = {}) {
  const normalizedPackId = String(packId || '').trim();
  if (!normalizedPackId) return null;
  const result = await loadPublicPackCatalog(options);
  return result.packs.find((pack) => pack && pack.pack_id === normalizedPackId) || null;
}
