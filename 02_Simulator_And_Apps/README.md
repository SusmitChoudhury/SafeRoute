# Part 2: Simulation Engine, Persistence & Interactive Applications

While **Part 1 ([`01_Main_Algorithms_Viva/`](../01_Main_Algorithms_Viva/README.md) & [`core/`](../core/))** contains the pure pathfinding, risk scoring, and look-ahead algorithms, **Part 2** packages those algorithms into an interactive real-time simulation platform across three layers:

| Layer | Folder | Key Modules | Responsibility |
|---|---|---|---|
| **Simulation Engine** | [`sim/`](../sim/) | `simulation.py`, `walker.py`, `incidents.py`, `logger.py`, `scripted_demo.py` | 7-state machine (`IDLE -> MOVING -> WARNING_1 -> WARNING_2 -> ARRIVED`), smooth polyline walker interpolation, SQLite incident CRUD, 6-step reroute pipeline |
| **Web Map Simulator** | [`tools/`](../tools/) | `web_server.py`, `make_seed_incidents.py`, `prepare_data.py`, `viva_quiz.py` | Zero-dependency Python HTTP + JSON REST API, Leaflet OSM/Satellite interactive map, Two-Point P1→P2 selector, live pointer/marker drag-and-drop, 8 Hz live terminal |
| **Desktop Visualizer** | [`ui/`](../ui/) | `pygame_app.py`, `map_renderer.py`, `panel.py`, `log_console.py`, `audio.py` | Hardware-accelerated Pygame desktop GUI (`python main.py`) with offline OSM tile basemap overlay |

---

## Launch Options

### 1. Localhost Web Simulator (Recommended Interactive Map UI)
```bash
python tools/web_server.py --port 8000
```
Open **http://localhost:8000** in any browser.

### 2. Desktop Pygame Simulator
```bash
python main.py
```

### 3. Automated Test Suite (`pytest`)
```bash
pytest -v
```
