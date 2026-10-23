import { useCallback, useEffect, useRef, useState } from "react";
import { useApi } from "../app/providers";
import { errorText, isAbort } from "./api";

export function useResource<T>(path: string | null) {
  const api = useApi();
  const [data, setData] = useState<T | null>(null);
  const [resolvedPath, setResolvedPath] = useState<string | null>(null);
  const [loading, setLoading] = useState(Boolean(path));
  const [error, setError] = useState("");
  const controller = useRef<AbortController | null>(null);
  const refresh = useCallback(async () => {
    controller.current?.abort();
    const current = new AbortController();
    controller.current = current;
    if (!path) {
      setData(null);
      setError("");
      setLoading(false);
      return;
    }
    setLoading(true);
    setError("");
    try {
      const value = await api.request<T>(path, { signal: current.signal });
      if (!current.signal.aborted) {
        setData(value);
        setResolvedPath(path);
      }
    } catch (err) {
      if (!isAbort(err) && !current.signal.aborted) {
        setError(errorText(err));
        setData(null);
        setResolvedPath(path);
      }
    } finally {
      if (!current.signal.aborted) setLoading(false);
    }
  }, [api, path]);
  useEffect(() => {
    setData(null);
    void refresh();
    return () => controller.current?.abort();
  }, [refresh]);
  return {
    data: resolvedPath === path ? data : null,
    loading: path !== null && (loading || resolvedPath !== path),
    error: resolvedPath === path ? error : "",
    refresh,
  };
}
