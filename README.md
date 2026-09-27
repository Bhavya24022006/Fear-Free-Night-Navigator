# Fear-Free Navigator

Safety-aware navigation for Indian cities. For any two points in a city, the app shows two routes, the **safer route** and the **faster route**, and how much safety the safer one gains for how many extra minutes at the chosen time of day.

## Quick start: run the demo

The repository includes the routes between Bengaluru's place buttons, computed in advance (`data/demo_cache/`), so the demo runs without the large data folder and on an ordinary laptop. For the recording itself, see [DEMO.md](DEMO.md).

You need [Python 3.11, 3.12 or 3.13](https://www.python.org/downloads/) (tick **Add python.exe to PATH** when installing), [Node.js 18 or newer](https://nodejs.org/) and [Git](https://git-scm.com/downloads).

**1. Get the code** (PowerShell):

```powershell
git clone <this repository's URL>
cd Fear-Free-Night-Navigator
```

**2. Install and start the backend** (first install takes a few minutes):

```powershell
python -m venv venv
venv\Scripts\activate
python -m pip install -r requirements.txt
python -m uvicorn api.main:app --host 0.0.0.0 --port 8000
```

Wait for `Application startup complete`, then leave this window open.

**3. Start the frontend** in a second PowerShell window, from the same folder:

```powershell
cd frontend
npm install
npm start
```

The app opens at http://localhost:3000. Next time, only the two start commands are needed: `venv\Scripts\activate` then the `uvicorn` line in one window, and `npm start` in `frontend` in the other.

**4. Use the place buttons.** Choose a start and a destination with the buttons under **Start from** and **Go to**; changing the time, travel mode, safety preference or Women Safety Mode then updates the routes at once. Clicking elsewhere on the map, or **My location**, needs the full data folder (below) and several minutes per route.

If PowerShell refuses to run `venv\Scripts\activate`, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once and try again. For other problems, see the notes under [Running the app](#running-the-app).

## Architecture

```text
┌──────────────────────────────┐       HTTP / JSON       ┌────────────────────────────────────────────┐
│ Frontend (React + Leaflet)   │ ──────────────────────▶ │ Backend (FastAPI, port 8000)               │
│ frontend/  · port 3000       │                         │ api/      /route /heatmap /cities /report  │
│ map, route comparison,       │                         │ routing/  graph cache, time-of-day weights,│
│ directions, risk map         │                         │           Dijkstra × 2                     │
└──────────────────────────────┘                         │ ai/ml/    XGBoost safety model, SHAP       │
                                                         └─────────────────────┬──────────────────────┘
                                                                               │ reads
                                                         ┌─────────────────────▼──────────────────────┐
                                                         │ data/  road graphs, feature stores,        │
                                                         │        night-light tiles, crime data       │
                                                         └────────────────────────────────────────────┘
```

**How a route is computed**

1. The city's road graph (from OpenStreetMap) is loaded once and kept in memory for an hour.
2. Each road segment gets:
   - night-time brightness (NASA VIIRS);
   - a crime density (city crime index plus crime zones);
   - a 0-100 safety score from the XGBoost model, which reads 32 features per segment from the city's feature store.
3. For the requested hour, the score is lowered by penalties for crime, darkness and closed shops. The penalties are small by day and largest between 00:00 and 06:00.
4. Each segment costs `α · length · 100 / safety + (1 − α) · travel time`, where α is the user's safety preference. The safety term is risk exposure, so a long risky stretch costs more than a short one. Each term is divided by its average over the city's segments, so α is the share of the cost given to safety. Dijkstra finds the cheapest path on this cost (safer route) and on travel time alone (faster route).
5. A route's safety score is its average per km. Its high-risk distance is the length on roads scoring under 40 at that hour (grades D and E).

If some data is missing, the app still runs: lighting is estimated from the road type, built-in crime priors are used, and a simple formula replaces the model.

| Folder                          | Contents                                                                                       |
| ------------------------------- | ---------------------------------------------------------------------------------------------- |
| `api/`                          | FastAPI app (`main.py`), endpoints (`routers/`), request and response schemas (`models/`)      |
| `routing/`                      | `city_router.py` (multi-city routing engine); `dijkstra.py`, `graph.py` (single-city helpers)  |
| `ai/ml/`                        | Feature definitions, model training, prediction, SHAP explanations, model files (`artifacts/`) |
| `ai/llm/`                       | Optional plain-language explanations                                                           |
| `ingestion/`                    | Scripts that build the data folder (road graphs, night lights, crime, feature stores)          |
| `frontend/`                     | React app (`src/components`, `src/hooks`)                                                      |
| `evaluation/`, `test_cities.py` | Benchmark and smoke test                                                                       |

## Requirements

- Python 3.11 to 3.13
- Node.js 18 or newer
- About 6-8 GB of free RAM for a large city (Bengaluru's road graph has about 930,000 segments)

## Running the app

These steps set up the full app, which routes between any two points and needs the data folder. For the demo alone, the [quick start](#quick-start-run-the-demo) is enough.

Run all commands from the project folder.

### 1. Data folder

Put the project data in a folder named `data` in the project root:

```text
data/
├── india/
│   ├── city_graphs/<city>.graphml           required: one road graph per city, e.g. bengaluru.graphml
│   └── features/<city>_feature_store.csv    needed for the ML safety scores
└── raw/
    ├── viirs/<city>.npy                     optional: night-light tile for the city
    ├── city_crime_index.json                optional
    └── city_crime_zones.json                optional
```

The city dropdown lists every `.graphml` file in `data/india/city_graphs/`.

### 2. Python environment

```powershell
python -m venv venv
venv\Scripts\activate
python -m pip install -r requirements.txt
```

> **Windows with Smart App Control:** if an import fails with _"An Application Control policy has blocked this file"_, delete the `venv` folder and recreate it so it reuses the packages already installed on your system, then add only the missing ones:
>
> ```powershell
> deactivate
> Remove-Item -Recurse -Force venv
> python -m venv --system-site-packages venv
> venv\Scripts\activate
> python -m pip install osmnx geopandas xgboost shap
> ```

Always start Python tools as `python -m <tool>` (as below) so they run inside the `venv`. A bare `uvicorn` command can pick up a copy from your main Python installation, which fails with `No module named 'osmnx'`.

### 3. Model

The safety model lives in `ai/ml/artifacts/` as `india_safety_model.pkl` or `safety_model.pkl`. If neither file is there, train one from the feature stores in `data/india/features/` (a few minutes):

```powershell
python -m ai.ml.train_india
```

### 4. Start the backend

```powershell
venv\Scripts\activate
python -m uvicorn api.main:app --host 0.0.0.0 --port 8000
```

Leave this window open. API documentation is at http://localhost:8000/docs.

### 5. Start the frontend

In a second window:

```powershell
cd frontend
npm install
npm start
```

The app opens at http://localhost:3000.

> **Low on memory?** The development server uses several hundred MB. Instead, build the app once and serve the static files with Python:
>
> ```powershell
> cd frontend
> $env:GENERATE_SOURCEMAP="false"; $env:REACT_APP_API_BASE_URL="http://127.0.0.1:8000"
> npm run build
> python -m http.server 3000 --directory build
> ```
>
> Use `127.0.0.1` rather than `localhost` for the API address: on Windows, `localhost` is tried over IPv6 first, which the API does not listen on, and every request waits for the fallback.

### 6. Use it

1. Pick a city. The first time a city is used, its road network is loaded and scored, which can take a few minutes for a large city; a message on the map shows progress.
2. Set a start (A) and a destination (B) by clicking the map, using a place button or "My location".
3. Choose the travel mode, time of travel and safety preference, or turn on Women Safety Mode.
4. Compare the safer (green) and faster (dashed blue) routes, then press **Start trip on the safer route** for turn-by-turn directions.

### 7. Instant routes for a demo (rebuilding them)

A route between two arbitrary points on a large city takes minutes. For a demo that uses the place buttons, every combination is computed in advance: each pair of places, each travel mode, each time period and each safety-slider value, plus the risk map. The repository ships these for Bengaluru; rebuild them after changing the data, the model or `routing/city_router.py`. Stop the backend first so the two processes don't both hold the road graph in memory, then run:

```powershell
python -m routing.demo_cache --city Bengaluru
```

The results go to `data/demo_cache/bengaluru/`. After the backend restarts, requests between place buttons, and the risk map, are answered from these files at once, and the road graph is not loaded unless you route between other points. If the graph, feature store, model, crime or night-light data, or `routing/city_router.py` changes, the stored routes are ignored until you run the command again. Files that are missing are not checked, so a copy without the data folder still uses the stored routes.

## Configuration

Optional settings go in a `.env` file (copy `.env.example`):

| Variable                 | Purpose                                                                                   |
| ------------------------ | ----------------------------------------------------------------------------------------- |
| `GROQ_API_KEY`           | Plain-language explanations in `ai/llm/explainer.py`; without it, rule-based text is used |
| `MAPILLARY_ACCESS_TOKEN` | Street imagery for `ingestion/fetch_all_features.py`                                      |
| `REACT_APP_API_BASE_URL` | API address for a production frontend build; the dev server already forwards to port 8000 |

## Adding more cities (optional)

```powershell
python -m ingestion.fetch_india_graph --city Pune                 # road graph from OpenStreetMap
python -m ingestion.fetch_viirs_real --city Pune                  # night-light tile from NASA
python -m ingestion.fetch_crime_real                              # crime index and zones for all cities
python -m ingestion.build_india_features_synthetic --city Pune    # fast feature store
python -m ai.ml.train_india                                       # retrain on all feature stores
```

`python -m ingestion.fetch_all_features --city Pune` builds a feature store from real OpenStreetMap points of interest instead (slower).

## API

| Method | Path             | Description                                                                                                                                                                                                               |
| ------ | ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| GET    | `/route/`        | Safer and faster routes, comparison and turn-by-turn directions. Parameters: `origin_lat`, `origin_lon`, `dest_lat`, `dest_lon`, `city`, `hour` (0-23), `alpha` (0-1), `mode` (`car`, `motorcycle`, `walking`, `cycling`) |
| GET    | `/heatmap/`      | Sampled `[lat, lon, score]` points for a city (`city`, `sample_n`)                                                                                                                                                        |
| GET    | `/cities/`       | Cities with a road graph                                                                                                                                                                                                  |
| GET    | `/cities/detect` | City for a GPS position (`lat`, `lon`)                                                                                                                                                                                    |
| POST   | `/report/`       | Save a report of an unsafe spot (`lat`, `lon`, `description`, `category`)                                                                                                                                                 |
| GET    | `/report/count`  | Number of saved reports                                                                                                                                                                                                   |
| GET    | `/health`        | Liveness check                                                                                                                                                                                                            |
