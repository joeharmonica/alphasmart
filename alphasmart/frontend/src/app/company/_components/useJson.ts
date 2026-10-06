"use client";

import { useEffect, useState } from "react";

type State<T> = { url: string; data: T | null; error: string | null };

/** Fetch JSON for `url`; loading is derived (no synchronous setState in the effect). */
export function useJson<T>(url: string | null) {
  const [state, setState] = useState<State<T>>({ url: "", data: null, error: null });

  useEffect(() => {
    if (!url) return;
    let alive = true;
    fetch(url)
      .then(async (r) => {
        const body = await r.json();
        if (!r.ok || (body && typeof body === "object" && "error" in body && Object.keys(body).length === 1)) {
          throw new Error(body?.error ?? `HTTP ${r.status}`);
        }
        return body as T;
      })
      .then((data) => alive && setState({ url, data, error: null }))
      .catch((e: Error) => alive && setState({ url, data: null, error: e.message }));
    return () => {
      alive = false;
    };
  }, [url]);

  const current = state.url === url;
  return {
    data: current ? state.data : null,
    error: current ? state.error : null,
    loading: !!url && !current,
  };
}
