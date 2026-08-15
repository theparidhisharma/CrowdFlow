import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  getProvider,
  resetBackendProvider,
  type DataSourceMode,
} from "@/services/provider";
import { ApiError } from "@/services/apiClient";
import type {
  HotspotStat,
  Incident,
  InfrastructureRecommendation,
} from "@/types/incident";
import { buildCrowdState, buildPredictions, formatClock } from "@/data/demo/scenario";
import { SIM_WINDOW_SECONDS } from "@/data/demo/venue";
import type { CrowdState, Zone } from "@/types/crowd";
import type { Prediction } from "@/types/prediction";

export type Speed = 1 | 2 | 5;

export type ConnectionStatus =
  | "DEMO"
  | "CONNECTING"
  | "ONLINE"
  | "OFFLINE"
  | "NO_DATA";

const MODE_STORAGE_KEY = "crowdflow.dataSource";

interface DemoStore {
  mode: "DEMO" | "LIVE";
  dataSource: DataSourceMode;
  setDataSource: (mode: DataSourceMode) => void;
  /** Forces an immediate re-read of the backend (used after a video analysis). */
  refreshBackend: () => void;
  connection: ConnectionStatus;
  connectionError: string | null;
  /** epoch ms of the last successful backend payload (null in demo mode) */
  lastUpdatedAt: number | null;
  incidents: Incident[];
  hotspots: HotspotStat[];
  infrastructure: InfrastructureRecommendation[];
  simSecond: number;
  clock: string;
  playing: boolean;
  speed: Speed;
  crowd: CrowdState;
  predictions: Prediction[];
  focusZoneId: string;
  selectedZoneId: string | null;
  interventionAppliedAt: number | null;
  interventionApplied: boolean;
  selectedInterventionIds: string[];
  play: () => void;
  pause: () => void;
  toggle: () => void;
  reset: () => void;
  setSpeed: (s: Speed) => void;
  seek: (second: number) => void;
  selectZone: (zoneId: string | null) => void;
  setSelectedInterventions: (ids: string[]) => void;
  applyIntervention: (ids: string[]) => void;
  zoneById: (id: string) => Zone | undefined;
  predictionFor: (id: string) => Prediction | undefined;
}

const DemoContext = createContext<DemoStore | null>(null);

const TICK_MS = 250;
/** Central backend refresh interval (single timer for the whole app). */
const BACKEND_POLL_MS = 3000;

function readStoredMode(): DataSourceMode {
  if (typeof window === "undefined") return "DEMO";
  return window.localStorage.getItem(MODE_STORAGE_KEY) === "BACKEND"
    ? "BACKEND"
    : "DEMO";
}

export function DemoStoreProvider({ children }: { children: ReactNode }) {
  const [simSecond, setSimSecond] = useState(150);
  const [playing, setPlaying] = useState(true);
  const [speed, setSpeed] = useState<Speed>(1);
  const [selectedZoneId, setSelectedZoneId] = useState<string | null>("corridor-c");
  const [interventionAppliedAt, setInterventionAppliedAt] = useState<number | null>(null);
  const [selectedInterventionIds, setSelectedInterventionIds] = useState<string[]>([]);
  const [dataSource, setDataSourceState] = useState<DataSourceMode>("DEMO");
  const [connection, setConnection] = useState<ConnectionStatus>("DEMO");
  const [connectionError, setConnectionError] = useState<string | null>(null);
  const [lastUpdatedAt, setLastUpdatedAt] = useState<number | null>(null);
  const [refreshTick, setRefreshTick] = useState(0);
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [hotspots, setHotspots] = useState<HotspotStat[]>([]);
  const [infrastructure, setInfrastructure] = useState<InfrastructureRecommendation[]>([]);
  const secondRef = useRef(simSecond);
  secondRef.current = simSecond;

  // Restore the last chosen source after hydration (avoids SSR mismatch).
  useEffect(() => {
    const stored = readStoredMode();
    if (stored !== "DEMO") setDataSourceState(stored);
  }, []);

  const refreshBackend = useCallback(() => {
    resetBackendProvider();
    setRefreshTick((t) => t + 1);
  }, []);

  const setDataSource = useCallback((next: DataSourceMode) => {
    setDataSourceState(next);
    setConnectionError(null);
    setConnection(next === "DEMO" ? "DEMO" : "CONNECTING");
    if (typeof window !== "undefined") {
      window.localStorage.setItem(MODE_STORAGE_KEY, next);
    }
  }, []);

  useEffect(() => {
    if (!playing) return;
    const id = window.setInterval(() => {
      setSimSecond((prev) => {
        const next = prev + (speed * TICK_MS) / 1000;
        return next >= SIM_WINDOW_SECONDS ? SIM_WINDOW_SECONDS : next;
      });
    }, TICK_MS);
    return () => window.clearInterval(id);
  }, [playing, speed]);

  // Derived state comes through the provider abstraction so the same UI works
  // unchanged against a live backend.
  const [crowd, setCrowd] = useState<CrowdState>(() => buildCrowdState(150, null));
  const [predictions, setPredictions] = useState<Prediction[]>(() =>
    buildPredictions(150, null),
  );

  // DEMO: recompute whenever the simulation cursor moves.
  useEffect(() => {
    if (dataSource !== "DEMO") return;
    let cancelled = false;
    const provider = getProvider("DEMO");
    const query = { simSecond, interventionAppliedAt };
    void Promise.all([
      provider.getCrowdState(query),
      provider.getPredictions(query),
    ]).then(([state, preds]) => {
      if (cancelled) return;
      setCrowd(state);
      setPredictions(preds);
      setConnection("DEMO");
      setConnectionError(null);
      setLastUpdatedAt(null);
    });
    return () => {
      cancelled = true;
    };
  }, [dataSource, simSecond, interventionAppliedAt]);

  // BACKEND: one central poll for the whole app.
  useEffect(() => {
    if (dataSource !== "BACKEND") return;
    let cancelled = false;
    const provider = getProvider("BACKEND");
    setConnection("CONNECTING");

    const fetchOnce = async () => {
      const query = { simSecond: secondRef.current, interventionAppliedAt: null };
      try {
        const [state, preds] = await Promise.all([
          provider.getCrowdState(query),
          provider.getPredictions(query),
        ]);
        if (cancelled) return;
        setCrowd(state);
        setPredictions(preds);
        setConnection("ONLINE");
        setConnectionError(null);
        setLastUpdatedAt(Date.now());
      } catch (error) {
        if (cancelled) return;
        const pipelineMissing = error instanceof ApiError && error.status === 503;
        setConnection(pipelineMissing ? "NO_DATA" : "OFFLINE");
        setConnectionError(
          error instanceof Error ? error.message : "Backend unreachable",
        );
      }
    };

    void fetchOnce();
    const id = window.setInterval(() => void fetchOnce(), BACKEND_POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [dataSource, refreshTick]);

  // Historical intelligence (incidents / hotspots / infrastructure) is loaded
  // once per data source — it changes far more slowly than the live state.
  const online = connection === "ONLINE";
  useEffect(() => {
    let cancelled = false;
    const provider = getProvider(dataSource);
    void Promise.all([
      provider.getIncidents().catch(() => [] as Incident[]),
      provider.getHotspots().catch(() => [] as HotspotStat[]),
      provider
        .getInfrastructureRecommendations()
        .catch(() => [] as InfrastructureRecommendation[]),
    ]).then(([inc, hot, infra]) => {
      if (cancelled) return;
      setIncidents(inc);
      setHotspots(hot);
      setInfrastructure(infra);
    });
    return () => {
      cancelled = true;
    };
  }, [dataSource, online]);

  const reset = useCallback(() => {
    setInterventionAppliedAt(null);
    setSelectedInterventionIds([]);
    setSelectedZoneId("corridor-c");
    setSimSecond(150);
    setPlaying(true);
    setSpeed(1);
  }, []);

  const applyIntervention = useCallback((ids: string[]) => {
    setSelectedInterventionIds(ids);
    setInterventionAppliedAt(secondRef.current);
    setPlaying(true);
  }, []);

  const value = useMemo<DemoStore>(
    () => ({
      mode: dataSource === "BACKEND" ? "LIVE" : "DEMO",
      dataSource,
      setDataSource,
      refreshBackend,
      connection,
      connectionError,
      lastUpdatedAt,
      incidents,
      hotspots,
      infrastructure,
      simSecond,
      clock: formatClock(simSecond),
      playing,
      speed,
      crowd,
      predictions,
      focusZoneId: selectedZoneId ?? "corridor-c",
      selectedZoneId,
      interventionAppliedAt,
      interventionApplied:
        interventionAppliedAt !== null && simSecond >= interventionAppliedAt,
      selectedInterventionIds,
      play: () => setPlaying(true),
      pause: () => setPlaying(false),
      toggle: () => setPlaying((p) => !p),
      reset,
      setSpeed,
      seek: (second: number) =>
        setSimSecond(Math.max(0, Math.min(SIM_WINDOW_SECONDS, second))),
      selectZone: setSelectedZoneId,
      setSelectedInterventions: setSelectedInterventionIds,
      applyIntervention,
      zoneById: (id: string) => crowd.zones.find((z) => z.id === id),
      predictionFor: (id: string) => predictions.find((p) => p.zoneId === id),
    }),
    [
      simSecond,
      playing,
      speed,
      crowd,
      predictions,
      selectedZoneId,
      interventionAppliedAt,
      selectedInterventionIds,
      reset,
      applyIntervention,
      dataSource,
      setDataSource,
      refreshBackend,
      connection,
      connectionError,
      lastUpdatedAt,
      incidents,
      hotspots,
      infrastructure,
    ],
  );

  return <DemoContext.Provider value={value}>{children}</DemoContext.Provider>;
}

export function useDemo(): DemoStore {
  const ctx = useContext(DemoContext);
  if (!ctx) throw new Error("useDemo must be used inside DemoStoreProvider");
  return ctx;
}
