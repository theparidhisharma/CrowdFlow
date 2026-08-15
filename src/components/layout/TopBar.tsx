import { Link } from "@tanstack/react-router";
import { useDemo } from "@/state/demo-store";
import { demoEvent } from "@/data/demo/venue";
import { cn } from "@/lib/utils";

const NAV = [
  { to: "/command-center", label: "Command Center" },
  { to: "/digital-twin", label: "Digital Twin" },
  { to: "/predictions", label: "Predictions" },
  { to: "/incidents", label: "Incidents" },
  { to: "/simulator", label: "Simulator" },
  { to: "/video-analysis", label: "Video Analysis" },
  { to: "/infrastructure", label: "Infrastructure" },
] as const;


export function TopBar() {
  const { clock, mode, crowd, dataSource, setDataSource, connection, connectionError } =
    useDemo();

  return (
    <header className="flex h-14 shrink-0 items-center gap-6 border-b border-border bg-panel px-4">
      <Link to="/" className="flex items-center gap-3">
        <BrandMark />
        <span className="leading-none">
          <span className="block font-mono text-[13px] font-bold tracking-[0.16em] text-foreground">
            CROWDFLOW INTELLIGENCE
          </span>
          <span className="mt-1 block font-mono text-[9px] tracking-[0.26em] text-muted-foreground">
            PREDICT. EXPLAIN. INTERVENE.
          </span>
        </span>
      </Link>

      <nav aria-label="Primary" className="hidden items-center gap-0.5 lg:flex">
        {NAV.map((item) => (
          <Link
            key={item.to}
            to={item.to}
            activeOptions={{ exact: false }}
            className="border-b-2 border-transparent px-3 py-2 font-mono text-[11px] tracking-[0.12em] text-muted-foreground uppercase transition-colors hover:text-foreground"
            activeProps={{
              className: "!border-info !text-foreground bg-panel-raised",
            }}
          >
            {item.label}
          </Link>
        ))}
      </nav>

      <div className="ml-auto flex items-center gap-4">
        <div
          className="hidden items-center border border-border bg-panel-raised md:inline-flex"
          role="group"
          aria-label="Data source"
        >
          {(["DEMO", "BACKEND"] as const).map((source) => (
            <button
              key={source}
              type="button"
              onClick={() => setDataSource(source)}
              aria-pressed={dataSource === source}
              className={cn(
                "px-2.5 py-1 font-mono text-[10px] tracking-[0.18em] transition-colors",
                dataSource === source
                  ? "bg-info/15 text-info"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              {source}
            </button>
          ))}
        </div>
        <span
          title={connectionError ?? undefined}
          className={cn(
            "hidden items-center gap-2 border px-2 py-1 font-mono text-[10px] tracking-[0.18em] md:inline-flex",
            connection === "OFFLINE"
              ? "border-critical/40 bg-critical/10 text-critical"
              : "border-info/40 bg-info/10 text-info",
          )}
        >
          <span className="size-1.5 rounded-full bg-current scan-pulse" aria-hidden />
          {connection === "OFFLINE"
            ? "BACKEND OFFLINE"
            : connection === "CONNECTING"
              ? "CONNECTING…"
              : `${mode} MODE`}
        </span>

        <label className="hidden flex-col md:flex">
          <span className="tech-label">EVENT</span>
          <select
            className="mt-0.5 border border-border bg-panel-raised px-2 py-1 font-mono text-[11px] text-foreground"
            defaultValue={demoEvent.id}
            aria-label="Select event"
          >
            <option value={demoEvent.id}>IPL MATCH — DELHI</option>
          </select>
        </label>
        <div className="hidden flex-col items-end sm:flex">
          <span
            className={cn(
              "flex items-center gap-1.5 font-mono text-[10px] tracking-[0.16em]",
              crowd.health.digitalTwin ? "text-safe" : "text-critical",
            )}
          >
            <span className="size-1.5 rounded-full bg-current" aria-hidden />
            SYSTEM ONLINE
          </span>
          <time className="font-mono text-lg leading-tight font-semibold tabular-nums">
            {clock}
          </time>
        </div>
      </div>
    </header>
  );
}

function BrandMark() {
  return (
    <svg width="26" height="26" viewBox="0 0 26 26" aria-hidden className="shrink-0">
      <rect x="0.75" y="0.75" width="24.5" height="24.5" stroke="var(--info)" fill="none" />
      <circle cx="13" cy="13" r="7.5" stroke="var(--info)" strokeOpacity="0.5" fill="none" />
      <circle cx="13" cy="13" r="3" fill="var(--critical)" />
      <path d="M2 13h4M20 13h4M13 2v4M13 20v4" stroke="var(--info)" strokeOpacity="0.8" />
    </svg>
  );
}
