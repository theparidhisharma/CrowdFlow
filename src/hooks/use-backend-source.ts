import { useCallback, useEffect, useState } from "react";
import { api, type ApiSource, type SourceMode } from "@/services/apiClient";
import { useDemo } from "@/state/demo-store";

const POLL_MS = 5000;

/**
 * Which artifacts the backend is currently serving (/api/source).
 *
 * Demo Mode is unaffected: it always behaves as the configured Digital Twin,
 * exactly as before.
 */
export function useBackendSource() {
  const { dataSource } = useDemo();
  const [source, setSource] = useState<ApiSource | null>(null);
  const [tick, setTick] = useState(0);

  const refresh = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    if (dataSource !== "BACKEND") {
      setSource(null);
      return;
    }
    let cancelled = false;
    const load = () =>
      api
        .source()
        .then((next) => {
          if (!cancelled) setSource(next);
        })
        .catch(() => undefined);
    void load();
    const id = window.setInterval(() => void load(), POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [dataSource, tick]);

  const mode: SourceMode =
    dataSource === "BACKEND" ? (source?.mode ?? "DIGITAL_TWIN") : "DIGITAL_TWIN";

  return {
    source,
    mode,
    label: mode === "SINGLE_CAMERA" ? "Single Camera" : "Digital Twin",
    isSingleCamera: mode === "SINGLE_CAMERA",
    refresh,
  };
}
