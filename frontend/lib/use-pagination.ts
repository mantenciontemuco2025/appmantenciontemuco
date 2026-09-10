"use client";

import { useCallback, useEffect, useRef, useState } from "react";

/**
 * usePagination — paginación tipo "Cargar más" contra endpoints que devuelven
 * arrays. El `fetcher` recibe (offset, pageSize) y devuelve una página.
 * `hasMore` se deduce de que la última página devuelva exactamente `pageSize`
 * items (edge: una página completa ⇒ presumiblemente hay más).
 *
 * Uso:
 *   const { items, loading, loadingMore, hasMore, error, loadMore, reload } =
 *     usePagination({ fetcher: (o, n) => api.get(`/api/maintenance?limit=${n}&offset=${o}`), deps: [filters] });
 */
export function usePagination<T>({
  fetcher,
  pageSize = 20,
  deps = [],
}: {
  fetcher: (offset: number, pageSize: number) => Promise<T[]>;
  pageSize?: number;
  /** Cuando cambian, se recarga la primera página. */
  deps?: unknown[];
}) {
  const [items, setItems] = useState<T[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(true);
  const [error, setError] = useState("");

  // El fetcher vive en un ref para no volver a disparar cargas en cada render
  // (el consumidor puede pasarlo inline, capturando filtros).
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;
  const offsetRef = useRef(0);
  const inFlight = useRef(false);

  const reset = useCallback(() => {
    offsetRef.current = 0;
    setItems([]);
    setHasMore(true);
    setError("");
  }, []);

  const loadFirst = useCallback(async () => {
    reset();
    setLoading(true);
    try {
      const page = await fetcherRef.current(0, pageSize);
      setItems(page);
      setHasMore(page.length === pageSize);
      offsetRef.current = page.length;
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al cargar los datos");
    } finally {
      setLoading(false);
    }
  }, [pageSize, reset]);

  const loadMore = useCallback(async () => {
    if (inFlight.current || !hasMore) return;
    inFlight.current = true;
    setLoadingMore(true);
    try {
      const page = await fetcherRef.current(offsetRef.current, pageSize);
      setItems((prev) => [...prev, ...page]);
      setHasMore(page.length === pageSize);
      offsetRef.current += page.length;
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al cargar más registros");
    } finally {
      setLoadingMore(false);
      inFlight.current = false;
    }
  }, [hasMore, pageSize]);

  // Carga inicial; se repite cuando cambian las dependencias del consumidor
  // (filtros, entre otros). El fetcher NO va en el arreglo a propósito.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => {
    loadFirst();
  }, deps);

  return { items, loading, loadingMore, hasMore, error, loadMore, reload: loadFirst };
}