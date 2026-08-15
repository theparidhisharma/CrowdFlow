# CrowdFlow Intelligence

Crowd-safety command centre: a React/TanStack Start dashboard on top of the
existing Python computer-vision pipeline.

The dashboard has **two data sources**, switchable at runtime from the toggle in
the top bar:

| Mode      | Source                                                   | Needs the API? |
| --------- | -------------------------------------------------------- | -------------- |
| `DEMO`    | Scripted scenario in `src/data/demo/` (IPL match, Delhi)   | No             |
| `BACKEND` | FastAPI read-only layer over the pipeline's CSV outputs    | Yes            |

The choice is remembered in `localStorage`. Everything the UI renders in
`BACKEND` mode comes from real CSV rows — the API adds no analysis and no mock
fallbacks.

---

## 1. Run the frontend

```bash
bun install
bun run dev            # http://localhost:8080
```

`.env` holds the API location:

```
VITE_API_URL=http://localhost:8000
```

`DEMO` mode works immediately with no backend running.

## 2. Run the API

From the **project root** (paths in the API resolve relative to it):

```bash
pip install -r backend/api/requirements.txt
uvicorn backend.api.main:app --host 0.0.0.0 --port 8000
```

Endpoints (all `GET`, all read-only):

| Endpoint               | Reads                                            |
| ---------------------- | ------------------------------------------------ |
| `/api/health`          | which pipeline artifacts exist                    |
| `/api/venue`           | `backend/venue_config.json`                       |
| `/api/crowd/current`   | `videos/zone_tracking.csv`                        |
| `/api/crowd/density`   | `videos/density_analysis.csv`                     |
| `/api/crowd/flow`      | `videos/zone_flow.csv` + `videos/flow_analysis.csv` |
| `/api/crowd/congestion`| `videos/congestion_analysis.csv` / `zone_congestion.csv` |
| `/api/warnings`        | `videos/early_warning.csv`                        |
| `/api/predictions`     | `videos/crowd_prediction.csv`                     |
| `/api/crowd/timeline`  | density + flow history                            |

If a CSV is missing the endpoint returns **503 `PIPELINE_NOT_RUN`** naming the
exact stage to run. The dashboard then shows **BACKEND OFFLINE** in the top bar
and keeps the last good state — it never invents data.

## 3. Produce real data

The API only reads what the pipeline writes into `videos/`. With
`videos/crowd.mp4` in place, run from the project root:

```bash
python backend/tracker.py            # -> videos/tracks.csv
python backend/zone_analysis.py      # -> videos/zone_tracking.csv
python backend/density_analysis.py   # -> videos/density_analysis.csv
python backend/zone_flow.py          # -> videos/zone_flow.csv
python backend/flow_analysis.py      # -> videos/flow_analysis.csv
python backend/congestion.py         # -> videos/congestion_analysis.csv
python backend/zone_congestion.py    # -> videos/zone_congestion.csv
python backend/early_warning.py      # -> videos/early_warning.csv
python backend/crowd_prediction.py   # -> videos/crowd_prediction.csv
```

Zones, areas and capacities come from `backend/venue_config.json`
(`define_zones.py` / `verify_zones.py` help you author it).

### No video yet?

`python backend/api/sample_data.py` writes CSVs with exactly the pipeline's
columns into `videos/`, so you can exercise `BACKEND` mode end to end. It is a
developer utility, is never imported by the API, and is overwritten the moment
you run the real pipeline.

---

## How the pieces fit

```text
videos/*.csv ──► backend/api (FastAPI, read-only)
                      │  JSON
                      ▼
        src/services/apiClient.ts
        src/services/backendProvider.ts ─┐
        src/services/demoProvider.ts ────┤ both implement CrowdDataProvider
                                         ▼
                          src/state/demo-store.tsx
                    (one central 3s poll in BACKEND mode)
                                         ▼
                             every page / component
```

Components never call `fetch`. They read the store, so the same UI renders demo
and live data unchanged.

**Backend-derived in `BACKEND` mode:** zone occupancy, density and density
level, capacity usage, entries/exits and net flow, congestion trend, risk score
and level, minutes-to-capacity, 5/10-minute forecasts, timeline history.

**Still demo-generated** (the Python pipeline does not produce them):
root-cause breakdown, intervention catalogue and simulation, historical
incidents and hotspots, infrastructure recommendations, crowd-report confidence.
They are listed in `DEMO_ONLY_FEATURES` in `src/services/backendProvider.ts`.

The Python backend in `backend/` (apart from the additive `backend/api/`
folder) is unmodified.
