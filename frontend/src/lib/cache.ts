import { useCallback, useEffect, useState } from 'react'

/**
 * Tiny client cache (lag plan Phase 1, §3.1 — before TanStack Query lands in
 * Phase 4). One entry per key:
 *  - cached(key, fetcher, ttl): fresh value → no request; stale/missing →
 *    one request, shared by every concurrent caller (in-flight dedupe).
 *  - useCached(): renders the cached value immediately, revalidates in the
 *    background when stale, re-renders every subscriber on update.
 *  - invalidate(prefix): next read refetches (after create/delete/save).
 * A failed refresh never wipes a good cached value.
 */

interface Entry<T> {
  value?: T
  ts: number
  inflight?: Promise<T>
  subs: Set<(v: T) => void>
}

const store = new Map<string, Entry<any>>()

function entry<T>(key: string): Entry<T> {
  let e = store.get(key)
  if (!e) {
    e = { ts: 0, subs: new Set() }
    store.set(key, e)
  }
  return e as Entry<T>
}

export function peek<T>(key: string): T | undefined {
  return store.get(key)?.value as T | undefined
}

export function isFresh(key: string, ttlMs: number): boolean {
  const e = store.get(key)
  return !!e && e.value !== undefined && Date.now() - e.ts < ttlMs
}

export function setCached<T>(key: string, value: T): void {
  const e = entry<T>(key)
  e.value = value
  e.ts = Date.now()
  e.subs.forEach(fn => fn(value))
}

export async function cached<T>(key: string, fetcher: () => Promise<T>, ttlMs: number, force = false): Promise<T> {
  const e = entry<T>(key)
  if (!force && e.value !== undefined && Date.now() - e.ts < ttlMs) return e.value
  if (e.inflight) return e.inflight
  e.inflight = fetcher()
    .then(v => {
      setCached(key, v)
      return v
    })
    .finally(() => {
      e.inflight = undefined
    })
  return e.inflight
}

/** Forget everything (logout: the next account must never see these values). */
export function clearCache(): void {
  store.forEach(e => {
    e.value = undefined
    e.ts = 0
  })
}

/** Mark entries stale (keeps the value so screens still render instantly). */
export function invalidate(prefix: string): void {
  store.forEach((e, k) => {
    if (k === prefix || k.startsWith(prefix)) e.ts = 0
  })
}

export function useCached<T>(key: string, fetcher: () => Promise<T>, ttlMs: number) {
  const [data, setData] = useState<T | undefined>(() => peek<T>(key))
  const [loading, setLoading] = useState(() => peek<T>(key) === undefined)
  const [error, setError] = useState<string | null>(null)

  const reload = useCallback(async (force = true) => {
    if (peek<T>(key) === undefined) setLoading(true)
    try {
      setData(await cached(key, fetcher, ttlMs, force))
      setError(null)
    } catch (err: any) {
      setError(err?.message || 'Request failed')
    } finally {
      setLoading(false)
    }
    // fetcher identity is intentionally ignored: one fetcher per key
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, ttlMs])

  useEffect(() => {
    const e = entry<T>(key)
    const sub = (v: T) => setData(v)
    e.subs.add(sub)
    setData(peek<T>(key))
    void reload(false)
    return () => {
      e.subs.delete(sub)
    }
  }, [key, reload])

  return { data, loading, error, reload, setData: (v: T) => setCached(key, v) }
}
