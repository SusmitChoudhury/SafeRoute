# SafeRoute Simulation

A Python desktop simulator for safe route planning on real OpenStreetMap street
networks. A walker, bike, or car travels through the LPU / Chiheru area
(Punjab, India). Users can drop accidents and danger zones on the map. When a
danger zone is within 500 m ahead, the software warns the traveller, recalculates
a risk-weighted route, and shows the new path with extra distance and time.

**University project** — B.Tech CSE, Lovely Professional University, course CSM216.

## Quick start

```bash
# 1. Create a virtual environment
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # Linux / macOS

# 2. Install dependencies
pip install -r requirements.txt

# 3. Download map data (needs internet, one time only)
python tools/prepare_data.py --center 31.2551,75.7025 --dist 1500

# 4. Run the simulator
python main.py
```

## Controls

| Key | Action |
|-----|--------|
| Left click | Set start / end / drop incident (depending on mode) |
| Right click | Remove incident |
| 1 / 2 / 3 | Walk / Bike / Car mode |
| Q W E R T | Incident type: accident / flooding / unsafe / construction / damage |
| Space | Start / Pause |
| + / - | Speed x1 / x10 / x50 |
| L | Toggle explain mode |
| H | Toggle heat-map |
| F5 | Run scripted demo |
| Esc | Reset |

## Testing & Benchmarks

```bash
# Run the complete test suite (35 automated tests)
pytest -v

# Run the algorithm benchmarks (Linear vs Binary, Dijkstra vs A*)
python core/search_benchmark.py
```

Benchmark plots are saved in `docs/benchmark_search.png` and `docs/benchmark_dijkstra_astar.png`.

## Viva Preparation Notes

Comprehensive plain-English module explanations, mathematical formulas, likely viva questions, and a 6-minute demonstration script are provided in [`docs/VIVA_NOTES.md`](docs/VIVA_NOTES.md).

## Data disclaimer

⚠️ **Incident data is SIMULATED (seed=42)** for demonstration purposes.
The system architecture accepts real data through the same SQLite table.

## Attribution

Map data © OpenStreetMap contributors.

