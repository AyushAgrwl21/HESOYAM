import { useEffect, useState } from "react";
import { getJson, messageFrom } from "../api/http";

const responseCache = new Map<string, unknown>();

export interface ResourceState<T> {
  status: "idle" | "loading" | "ready" | "error";
  data: T | null;
  errorMessage: string | null;
  retry: () => void;
}

export function useGet<T>(path: string | null, parse: (value: unknown) => T): ResourceState<T> {
  const [retryToken, setRetryToken] = useState(0);
  const [state, setState] = useState<Omit<ResourceState<T>, "retry">>(() => {
    if (path !== null && responseCache.has(path)) {
      return { status: "ready", data: responseCache.get(path) as T, errorMessage: null };
    }
    return {
      status: path === null ? "idle" : "loading",
      data: null,
      errorMessage: null,
    };
  });

  useEffect(() => {
    if (path === null) {
      setState({ status: "idle", data: null, errorMessage: null });
      return;
    }
    if (responseCache.has(path)) {
      setState({ status: "ready", data: responseCache.get(path) as T, errorMessage: null });
      return;
    }
    const abortController = new AbortController();
    setState({ status: "loading", data: null, errorMessage: null });
    getJson(path, abortController.signal)
      .then((body) => {
        if (abortController.signal.aborted) {
          return;
        }
        const parsed = parse(body);
        responseCache.set(path, parsed);
        setState({ status: "ready", data: parsed, errorMessage: null });
      })
      .catch((error: unknown) => {
        if (abortController.signal.aborted) {
          return;
        }
        setState({ status: "error", data: null, errorMessage: messageFrom(error) });
      });
    return () => abortController.abort();
  }, [path, parse, retryToken]);

  return {
    ...state,
    retry: () => {
      if (path !== null) {
        responseCache.delete(path);
      }
      setRetryToken((current) => current + 1);
    },
  };
}
