SafeRoute Simulation - Complete Build Plan & Specification
Real-map simulation with live danger detection, automatic rerouting and 
an algorithm log panel
10 November 2026
0. How to Use This Document
This file is the single source of truth for the project. It is written so that a human (a teammate 
or the viva examiner) and an AI coding assistant can both read it and arrive at the same 
understanding.
Two-AI workflow
Step
Who
What happens
1
Claude
Produces this plan and the Antigravity 
prompt (done in this step). Writes no 
application code yet.
2
You
Review this plan. Say “start building” 
when you are happy with it.
3
Claude
Generates the project folders and files 
phase by phase (Section 12).
4
You
Download the project and open it in 
Google Antigravity (or any agentic 
IDE).
5
Antigravity
Runs, tests, debugs and finishes the 
code using the prompt in 
ANTIGRAVITY_PROMPT.md and 
this plan as its reference.
Rule for both AIs: if the code and this plan disagree, stop and tell the user. Do not silently 
change the design.
1. Project Vision
1.1 One-paragraph description
SafeRoute is a Python desktop simulator. A walker (or bike, or car) travels along a real street 
network of the LPU / Chiheru area, drawn over a real map image. The user can drop accidents, 
damaged roads and unsafe zones onto the map at any time. The software looks 500 m ahead 
along the planned route; when a danger zone is detected it raises Warning 1, recalculates the 
route using a risk-weighted Dijkstra search, and raises Warning 2 with the new path and its 
extra distance and time. A live log panel on the right shows every calculation the algorithm 
performs, in real time, so the examiner can see exactly how the software thinks.

1.2 Your requirements and where each one is delivered
#
Your requirement
Delivered by
1
A cursor / human walking on a real 
map
ui/map_renderer.py, 
sim/walker.py
2
Deploy accidents and danger zones
Click-to-drop incidents: 
sim/incidents.py, UI input mode
3
Detect the danger 500 m before 
reaching it
core/lookahead.py (binary 
search over entry distances)
4
Automatically change direction, 
suggest a new path, show two warnings
sim/simulation.py state 
machine + core/router.py
5
Shortest distance, travel time, and time 
at walking / bike / car speeds
core/travel_model.py + stats 
card
6
Live logs on the left or right showing 
the algorithm’s calculations
sim/logger.py + 
ui/log_console.py
7
Real-life history: many accidents or a 
damaged road make a road riskier
Historical incidents in SQLite feeding 
core/risk_model.py
8
Everything explainable in the viva
Explain mode, unit tests, this document
2. Key Design Decisions (Final)
These are decisions, not options. Each has a reason you can quote in the viva.
Decision
Choice
Why
Main language
Python 3.10+
Required by the syllabus and by you.
Simulation window
Pygame
Syllabus Unit 3 (coordinate system, 
Surface/Rect, event handling, state 
management). Smooth animation 
without the lag we saw in 
tkintermapview.
Launcher / setup screen
Tkinter
Syllabus Unit 2 (widgets, geometry 
managers, event binding).
Map image
Pre-rendered OpenStreetMap basemap 
via contextily, saved once as a PNG
No live tile calls during the demo, so it 
cannot lag or fail on the day.
Routing
Our own Dijkstra and A* written 
with heapq; NetworkX used only to 
cross-check
A hand-written algorithm can log every 
step and can be explained line by line. 
A one-line library call cannot.
Risk scoring
Rule-based formula (no machine 
learning)
Transparent, explainable, matches 
what you already told the teacher.
Search benchmark
bisect (binary) vs linear scan on the 
look-ahead index
Syllabus Unit 5 (linear vs binary 
search, time module, performance 
analysis).
Data storage
SQLite + CSV
Built into Python, zero setup, 
queryable.
Web languages (HTML / CSS / JS)
Not used
Adds a second language to defend in 
the viva and needs a Python-to-
browser bridge. Listed as future scope 
only.

3. Syllabus Mapping (CSM216)
Syllabus unit
Where it appears in the project
Core Python and algorithmic thinking: I/O, control flow, 
loops, data structures, random, time and space complexity
Dijkstra with a priority queue, complexity analysis, seeded 
random for demo incidents
Tkinter: widgets, geometry managers, event binding, event 
loop
Launcher window: choose mode, speed, scenario, start the 
simulation
Pygame: coordinate system, Surface and Rect, event 
handling, state management
The simulation window and the IDLE / MOVING / 
WARNING / REROUTING / ARRIVED state machine
NumPy, Pandas, Matplotlib
Vectorised distance maths, incident DataFrames, benchmark 
and heat-map plots
Searching algorithms, time module, performance analysis
Linear vs binary look-ahead search, Dijkstra vs A* node 
counts, timing
Advanced Tkinter grid layouts and styling
Launcher layout using grid()
Course outcomes: CO1 (syntax, classes), CO2 (NumPy / Pandas / Matplotlib), CO3 (Tkinter), 
CO4 (linear vs binary search), CO5 (Pygame), CO6 (real-world project).
4. System Architecture
4.1 Window layout
Simulation window: map on the left, stats card, controls and live log on the right
4.2 Layers
1.
Data layer - OSM graphs (walk, bike, drive) cached as GraphML; basemap PNG; SQLite 
incident store.
2.
Core layer (pure Python, no Pygame) - graph loading, travel-time model, risk model, 
Dijkstra, A*, look-ahead index, benchmark. Fully unit-testable.

3.
Simulation layer - walker, tick loop, state machine, logger.
4.
UI layer - Pygame map view, side panel, log console, Tkinter launcher.
The core layer never imports Pygame or Tkinter. This is what keeps the code explainable and 
testable.
4.3 Folder structure
saferoute/
├── main.py                    # entry point: starts launcher, then simulation
├── config.py                  # every tunable number in one place
├── requirements.txt
├── README.md
├── core/
│   ├── graph_loader.py        # download/cache/load graphs, snap points to nodes
│   ├── travel_model.py        # speeds per mode, edge travel times
│   ├── risk_model.py          # Incident dataclass, edge risk, edge weight
│   ├── dijkstra.py            # our Dijkstra (heapq) with optional step trace
│   ├── astar.py               # our A* with admissible heuristic
│   ├── router.py              # compute_route(), compare_modes(), reroute()
│   ├── lookahead.py           # route polyline, zone entry distance, bisect query
│   └── search_benchmark.py    # linear vs binary, Dijkstra vs A*, plots
├── sim/
│   ├── simulation.py          # state machine and tick loop
│   ├── walker.py              # moves along the route polyline
│   ├── incidents.py           # SQLite-backed incident store
│   └── logger.py              # SimLogger: levels, ring buffer, file sink
├── ui/
│   ├── launcher.py            # Tkinter start window
│   ├── pygame_app.py          # Pygame main loop and event handling
│   ├── map_renderer.py        # basemap, roads, routes, zones, walker drawing
│   ├── panel.py               # stats card and control buttons
│   ├── log_console.py         # scrolling coloured log view
│   └── audio.py               # alert tones (numpy + pygame.mixer)
├── tools/
│   ├── prepare_data.py        # one-off download of graphs and basemap
│   └── make_seed_incidents.py # generates simulated incidents on real edges
├── data/
│   ├── incidents_seed.csv
│   └── cache/                 # graph_walk.graphml, graph_bike.graphml, 
graph_drive.graphml, basemap.png, basemap_meta.json
├── db/saferoute.db
├── logs/                      # run_YYYYMMDD_HHMMSS.log
├── tests/
│   ├── test_dijkstra.py
│   ├── test_risk_model.py
│   ├── test_lookahead.py
│   └── test_travel_model.py
└── docs/                      # this plan, diagrams, viva notes
5. Data Pipeline and Coordinate Systems
5.1 One-time preparation
python tools/prepare_data.py --center 31.2551,75.7025 --dist 1500
This downloads the walk, bike and drive graphs (radius 1500 m around the centre), renders the 
basemap PNG, and saves everything to data/cache/. After this the application runs fully 
offline.

5.2 Three coordinate systems (the most common source of bugs)
System
Use
Units
EPSG:4326 (lat / lon)
Storage, user input, SQLite
degrees
UTM (chosen automatically by 
ox.project_graph)
All distance maths: lengths, radii, 
look-ahead
metres
EPSG:3857 (Web Mercator)
Matching the basemap image to pixels
map-projection metres (distorted, 
about 1.17x at this latitude)
Rule: never measure a distance in EPSG:3857 or in degrees. Measure in UTM. Convert to 
pixels only when drawing.
Pixel mapping, using the basemap extent (xmin, xmax, ymin, ymax) returned by 
contextily.bounds2img and image size W x H:
px = (X3857 - xmin) / (xmax - xmin) * W
py = (ymax - Y3857) / (ymax - ymin) * H
5.3 Data-quality rules (flag, never silently fix)
The software must report these conditions in the log as WARN, not hide them:
Condition
Log message
Start or end snaps more than 50 m from the nearest graph 
node
WARN snap distance 83 m - check OSM 
coverage here
Edges missing a speed tag, so a default speed was assumed
WARN speed assumed for 312 of 12034 edges 
(drive)
Incidents are simulated, not real
WARN incident data is SIMULATED (seed=42) 
shown at startup and in the panel footer
Graph disconnected between start and end
WARN no path in blocked graph - using 
penalty fallback
Basemap tiles unavailable
WARN basemap missing - drawing road 
network only
6. Algorithms in Detail
6.1 The graph
Nodes are intersections. Edges are road segments. Every edge has length (metres) and, after 
travel_model runs, speed_mps and base_time (seconds) for the chosen mode.
6.2 Travel-time model (walk / bike / car)
Mode
Speed rule
Network
Walk
5 km/h = 1.39 m/s
walk graph
Bike
15 km/h = 4.17 m/s
bike graph
Car
OSM maxspeed if present, else 
default by road class (residential 30, 
service 15, primary 50 km/h)
drive graph
base_time(edge) = length(edge) / speed(edge)          # seconds
ETA(route)      = sum of base_time over the route's edges

The stats card shows the ETA for all three modes at once by running the router on each 
graph for the same start and end. This answers “how long if I walk, bike or drive”.
6.3 Incident types
Type
Default severity (1-5)
Default radius
Blocks vehicles?
accident
4
150 m
yes
flooding
4
200 m
yes
unsafe_area (crime)
3
200 m
no
construction
2
100 m
yes
road_damage (pothole)
2
60 m
no
Mode sensitivity multipliers (how much each type matters to each mode):
Type
Walk
Bike
Car
accident
1.0
1.0
1.0
flooding
0.8
1.0
1.0
unsafe_area
1.2
0.8
0.3
construction
0.6
0.8
1.0
road_damage
0.4
1.2
0.9
6.4 Risk model (the formula the log will print)
For edge e and incident i with centre c_i, radius R_i, severity s_i, mode multiplier 
m(type_i, mode):
d_ei = shortest distance from edge e's geometry to c_i          (metres)
f    = max(0, 1 - d_ei / R_i)                                   (1 at the centre, 0 at the 
edge of the zone)
r_e  = sum over i of  s_i * m(type_i, mode) * f * age_factor_i  (risk of the edge)
r_e  = r_e + kappa * ln(1 + accidents_on_edge)                  (chronic accident roads)
w_e  = base_time_e * (1 + lambda * r_e)                         (edge weight in seconds-
equivalent)
w_e  = infinity                                                 if a blocking incident is 
within 40 m of e (vehicles only)
•
lambda = 2.0 (how strongly risk is avoided; tunable in config.py)
•
kappa = 0.3
•
age_factor = exp(-age_days / 180) for historical incidents, 1.0 for live ones 
(old incidents fade)
Because w_e >= base_time_e, the weight never drops below the real travel time. That keeps 
A* admissible (Section 6.6).
Fallback: if no path exists once blocked edges are removed (for example the destination is 
inside the zone), re-run with blocked edges given a penalty of x50 instead of infinity, choose 
the least-risk path, and log WARN.
6.5 Dijkstra (our implementation)
dijkstra(G, src, dst, weight_fn):
    dist = {src: 0};  prev = {};  heap = [(0, src)]
    explored = 0;  relaxations = 0

    while heap:
        d, u = heappop(heap)
        if d > dist[u]: continue            # stale heap entry
        explored += 1
        if u == dst: break
        for each edge (u, v, key):
            w = weight_fn(u, v, key)
            if w == infinity: continue
            relaxations += 1
            if d + w < dist.get(v, infinity):
                dist[v] = d + w;  prev[v] = u
                heappush(heap, (d + w, v))
    return path rebuilt from prev, total cost, explored, relaxations, elapsed_ms
Complexity: O((V + E) log V) with a binary heap. Space O(V).
Explain mode: when switched on, the function also records the first 12 heap pops (node, 
tentative distance) and the first relaxations of the start node, and sends them to the log. This is 
the “algorithm thinking” the teacher sees.
6.6 A* (our implementation)
Same as Dijkstra but the heap key is g + h, where h(n) = euclidean_distance(n, 
dst) / v_max (seconds). Because w_e >= base_time_e >= length / v_max, the 
heuristic never overestimates, so A* still returns the optimal path while exploring fewer nodes. 
The log prints both counts:
CALC dijkstra explored 1204 nodes, 3812 relaxations, 8.3 ms
CALC astar    explored  377 nodes, 1190 relaxations, 3.1 ms  (same cost: 1426 m)
The simulation uses A* for routing and Dijkstra for the explain-mode demonstration and cross-
checks. Both are tested against NetworkX.
6.7 Look-ahead detection (the 500 m rule)
Given the route as a polyline of UTM points P_0 ... P_n and cumulative distances D_0 ... 
D_n:
1.
Entry distance of an incident. For each segment A -> B solve the line-circle 
intersection |A + u(B - A) - c|^2 = R^2 for u in [0,1]. The smallest valid u on 
the first intersecting segment gives s_enter = D_A + u * |B - A|. Vectorised 
with NumPy.
2.
Index. Collect (s_enter, incident_id) for every incident the route touches and 
sort by s_enter. Build this once per route (and again after every reroute or new 
incident).
3.
Query on every tick. With the walker at distance s_now along the route:
lo = bisect_left(entry_keys, s_now)
hits = []
while lo < len(entry_keys) and entry_keys[lo] <= s_now + LOOKAHEAD_M:   # 500 m
    hits.append(entry_ids[lo]);  lo += 1
4.
Hysteresis. Each incident is allowed to trigger Warning 1 once per route. After a reroute 
the set is cleared for the new route.

Query cost is O(log I + k) against O(I) for a linear scan, where I is the number of incidents on 
the route. The benchmark module plots both for I from 10 to 100,000 synthetic incidents.
Honest note for the viva: with the handful of incidents in a live demo, both methods 
take microseconds. The binary search advantage appears at large I, which is why the 
benchmark uses synthetic data. Say this before the examiner asks.
The walker position itself also uses bisect on the cumulative-distance array to find the 
current segment in O(log n) per tick.
6.8 Rerouting rule
A walker cannot teleport. When Warning 1 fires:
1.
Identify the next node ahead on the current edge; this becomes the new origin.
2.
Recompute edge risks with all active incidents, then run A* from that node to the 
destination.
3.
Compare old vs new: extra distance, extra time, change in total risk.
4.
Splice: finish the current edge, then follow the new path.
5.
Raise Warning 2 with those numbers.
7. Simulation Engine
7.1 State machine
Detect-and-reroute state machine
State
Entered when
Exits when
IDLE
App starts or Reset
Start and end are set and the user 
presses Space
ROUTING
Start pressed or reroute requested
Path computed
MOVING
Route ready
Look-ahead hit, destination reached, or 

State
Entered when
Exits when
paused
WARNING_1
Incident within 500 m on the route
Reroute begins (immediately, one 
frame later)
REROUTING
After Warning 1
New path found
WARNING_2
New path found
Banner shown for 3 s of sim time, then 
MOVING
ARRIVED
Walker reaches destination
Reset
7.2 Tick loop
each frame (60 FPS target):
    real_dt = clock.tick(60) / 1000
    sim_dt  = real_dt * time_scale            # x1, x10, x50 so a 15-minute walk fits a 60-
second demo
    handle_events()                           # mouse, keyboard
    simulation.update(sim_dt)                 # state machine, walker, look-ahead, log
    renderer.draw(simulation)                 # map, routes, zones, walker, panel, log
Fixed rule: simulation logic uses sim_dt only; drawing never changes state.
7.3 Controls
Input
Action
Left click (Start mode)
Set start point
Left click (End mode)
Set destination
Left click (Incident mode)
Drop an incident of the selected type at that spot
Right click on an incident
Remove it (the route is rechecked)
1 / 2 / 3
Walk / Bike / Car
Q W E R T
Select incident type: accident / flooding / unsafe / 
construction / damage
Space
Start / pause
+ / -
Simulation speed x1 / x10 / x50
L
Toggle explain mode (verbose algorithm log)
H
Toggle risk heat-map
F5
Run the scripted demo scenario
Esc
Reset
8. Live Log Panel (the part you show the teacher)
8.1 Log line format
[mm:ss.s] LEVEL  module     message
Level
Colour
Meaning
INFO
blue
Normal progress (position, 
graph loaded)
CALC
yellow
A number the algorithm 
computed
ROUTE
green
A route was produced or 
changed
WARN
orange
Data-quality or Warning 1 / 

Level
Colour
Meaning
Warning 2 events
ALERT
red
Incident detected or entered
ERROR
magenta
Something failed
The log is a ring buffer of the last 500 lines shown in the panel, and every line is also written 
to logs/run_<timestamp>.log so you can show the file as evidence.
8.2 Sample transcript (target behaviour)
[00:00.0] INFO   startup     SafeRoute simulator v1.0, mode=walk, seed=42
[00:00.0] WARN   data        incident data is SIMULATED (seed=42)
[00:00.4] INFO   graph       walk graph loaded: 4812 nodes, 12034 edges (from cache)
[00:00.4] INFO   snap        start -> node 3281 (12.4 m), end -> node 5920 (8.1 m)
[00:00.5] CALC   dijkstra    explored 1204 nodes, 3812 relaxations, 8.3 ms, cost 1426 m
[00:00.5] CALC   astar       explored 377 nodes, 1190 relaxations, 3.1 ms, cost 1426 m
[00:00.5] CALC   modes       walk 1426 m 17.1 min | bike 1488 m 5.9 min | car 1812 m 3.6 
min
[00:00.5] ROUTE  router      route 1 chosen: 1426 m, 61 nodes, risk 0.00
[00:12.0] INFO   walker      312 m / 1426 m  speed 1.39 m/s  ETA 13.1 min
[00:15.0] INFO   incident    #7 accident dropped at (31.2562, 75.7031), radius 150 m, 
severity 4
[00:15.0] CALC   lookahead   incident #7 enters route at s = 912 m; walker at s = 436 m; 
gap 476 m
[00:15.0] ALERT  lookahead   danger zone within 500 m (476 m) - accident #7
[00:15.0] WARN   WARNING-1   danger ahead - recalculating route
[00:15.0] CALC   risk        edge (3290 -> 3295): t = 60.6 s, r = 0.90, w = 60.6 * (1 + 2.0 
* 0.90) = 169.7 s
[00:15.0] CALC   astar       explored 412 nodes, 1301 relaxations, 3.6 ms, cost 1590 m
[00:15.0] ROUTE  router      route 2 chosen: 1590 m, 67 nodes, risk 0.11
[00:15.0] CALC   compare     extra distance +164 m, extra time +1.9 min, risk 0.90 -> 0.11
[00:15.0] WARN   WARNING-2   rerouted: new path avoids incident #7 (+164 m, +1.9 min)
[01:40.0] INFO   walker      destination reached in 17.4 min (sim time)
[01:40.0] INFO   summary     distance 1590 m, reroutes 1, incidents avoided 1, warnings 2
All numbers above are illustrative; real values come from the code at run time.
8.3 Explain mode (press L)
Adds, for the routing call only: the first 12 priority-queue pops with node id and tentative cost, 
the first relaxations from the start node, and the final path as a node list. This is the slide-free 
way to explain Dijkstra live.
9. Data Layer
9.1 SQLite schema
CREATE TABLE incidents (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    type        TEXT    NOT NULL CHECK (type IN
                ('accident','flooding','unsafe_area','construction','road_damage')),
    lat         REAL    NOT NULL,
    lon         REAL    NOT NULL,
    severity    INTEGER NOT NULL CHECK (severity BETWEEN 1 AND 5),
    radius_m    REAL    NOT NULL,
    blocking    INTEGER NOT NULL DEFAULT 0,
    source      TEXT    NOT NULL CHECK (source IN ('historical','live','simulated')),
    created_at  TEXT    NOT NULL,          -- ISO 8601

    active      INTEGER NOT NULL DEFAULT 1
);
9.2 Seed data
tools/make_seed_incidents.py picks random edges of the walk graph (seeded random, 
seed 42), places a historical incident at each edge’s midpoint so every incident really sits on a 
road, and writes data/incidents_seed.csv. Every row has source = simulated. The 
README and the UI footer both say so.
Real-life history effect: several seed accidents are deliberately placed on the same road so the 
kappa * ln(1 + accidents_on_edge) term makes that road a chronic hot-spot, 
demonstrating “many accidents on one road”.
10. Module Contracts (function signatures)
# core/graph_loader.py
def load_graph(mode: str) -> "nx.MultiDiGraph": ...             # projected (UTM), with 
lat/lon kept
def snap_to_node(G, lat: float, lon: float) -> tuple[int, float]: ...   # (node_id, 
snap_distance_m)
# core/travel_model.py
MODE_SPEED_MPS = {"walk": 1.39, "bike": 4.17}
def add_travel_times(G, mode: str) -> dict: ...                  # returns 
{"assumed_speed_edges": n, "total_edges": m}
# core/risk_model.py
@dataclass
class Incident: id: int; type: str; x: float; y: float; severity: int; radius_m: float; 
blocking: bool; age_days: float
def compute_edge_risk(G, incidents: list[Incident], mode: str) -> dict: ...   # {(u,v,k): 
r_e}
def make_weight_fn(G, risk: dict, mode: str, lam: float = 2.0): ...          # returns 
f(u,v,k) -> seconds or inf
# core/dijkstra.py and core/astar.py
@dataclass
class PathResult: path: list[int]; cost: float; length_m: float; explored: int; 
relaxations: int; elapsed_ms: float; trace: list
def dijkstra(G, src: int, dst: int, weight_fn, explain: bool = False) -> PathResult: ...
def astar(G, src: int, dst: int, weight_fn, v_max: float, explain: bool = False) -> 
PathResult: ...
# core/router.py
def compute_route(G, src, dst, incidents, mode) -> PathResult: ...
def compare_modes(origin_latlon, dest_latlon, incidents) -> dict: ...         # {"walk": 
{...}, "bike": {...}, "car": {...}}
def reroute(G, current_node_ahead, dst, incidents, mode, old: PathResult) -> 
tuple[PathResult, dict]: ...
# core/lookahead.py
def route_polyline(G, path: list[int]) -> tuple["np.ndarray", "np.ndarray"]: ...   # points 
(n,2), cumulative metres (n,)
def zone_entry_distance(points, cum, centre, radius) -> float | None: ...
def build_entry_index(points, cum, incidents) -> "EntryIndex": ...                 # sorted 
keys + ids
def query_ahead(index, s_now: float, lookahead_m: float = 500.0) -> list[int]: ...
# core/search_benchmark.py

def linear_query(keys, s_now, L) -> list[int]: ...
def binary_query(keys, s_now, L) -> list[int]: ...
def run_benchmark(sizes=(10, 100, 1000, 10000, 100000), repeats=200) -> "pd.DataFrame": ...
# sim/logger.py
class SimLogger:
    def log(self, level: str, module: str, msg: str, sim_time: float) -> None: ...
    def lines(self, n: int = 500) -> list[tuple[str, str]]: ...                   # (level, 
text)
11. Configuration (config.py)
Name
Default
Meaning
CENTER_LATLON
(31.2551, 75.7025)
Map centre (approximate; verify on 
the map)
RADIUS_M
1500
Download radius
LOOKAHEAD_M
500
Detection distance
LAMBDA_RISK
2.0
Risk avoidance strength
KAPPA_HISTORY
0.3
Chronic-road weight
BLOCK_RADIUS_M
40
Distance at which a blocking incident 
closes an edge
DEFAULT_START_LATLON
(31.2540, 75.7010)
Law Gate area (approximate; verify)
DEFAULT_END_LATLON
(31.2565, 75.7038)
LPU main area (approximate; verify)
TIME_SCALES
(1, 10, 50)
Simulation speed options
SNAP_WARN_M
50
Snap-distance warning threshold
RANDOM_SEED
42
Reproducible demo
WINDOW_SIZE
(1600, 900)
Pygame window
12. Build Phases and Acceptance Tests
Each phase ends with a check. Do not start the next phase until the check passes.
Phase
Deliverable
Acceptance check
0
Project skeleton, 
requirements.txt, config.py, 
README
python -c "import osmnx, 
networkx, pygame, shapely, 
numpy, pandas, scipy, 
contextily" succeeds
1
tools/prepare_data.py, 
graph_loader.py
Three GraphML files and 
basemap.png exist; reload takes 
under 2 s; node and edge counts logged
2
map_renderer.py + static Pygame 
view
Window shows the basemap with the 
road network overlaid and aligned (a 
known junction lands on the same 
pixel in both)
3
dijkstra.py, astar.py, tests
On 100 random start-end pairs, our 
cost equals NetworkX 
shortest_path_length to 6 
decimals; A* cost equals Dijkstra cost
4
risk_model.py, incidents.py, 
SQLite
Dropping an incident on the route 
changes edge weights; unit tests pass 
for blocking and fallback

Phase
Deliverable
Acceptance check
5
walker.py, travel_model.py, 
logger.py, simulation.py (no 
look-ahead yet)
Walker follows the route at 1.39 m/s; 
ETA for walk, bike and car shown and 
plausible; log file written
6
lookahead.py, state machine, two 
warnings, audio.py
Dropping an accident 600 m ahead 
triggers Warning 1 at about 500 m and 
Warning 2 with a different route; no 
repeat trigger
7
panel.py, log_console.py, 
launcher.py, heat-map
Right-hand panel shows stats and 
coloured live log; Tkinter launcher 
starts the simulation
8
search_benchmark.py, scripted 
demo (F5), docs
Benchmark graph saved; F5 reproduces 
the demo identically with seed 42
9 (stretch)
Manual walking mode (arrow keys 
along graph edges), zoom and pan, PDF 
session report
Only if phases 0-8 are finished
13. Testing Plan
Test
What it proves
test_dijkstra.py
Our Dijkstra equals NetworkX on 100 random pairs; handles 
unreachable nodes; ignores infinite-weight edges
test_risk_model.py
f equals 1 at the centre and 0 at the radius; blocking works 
for car, not for walk; ageing reduces old incidents
test_lookahead.py
Entry distance on a straight synthetic route equals the 
analytic value; bisect and linear queries return identical 
sets for 10,000 random cases
test_travel_model.py
1,000 m takes 720 s walking and 240 s biking
Manual
Demo scenario (F5) twice in a row gives identical logs apart 
from timestamps
14. Viva Demonstration Script (about 6 minutes)
Time
Action
What you say
0:00
Launcher: pick Walk, speed x10, press 
Start
“This is a simulator of our SafeRoute 
algorithm on the real LPU street 
network.”
0:30
Point at the log: graph loaded, 
snapping, Dijkstra counts
“Every number you see on the right is 
calculated live by our own Dijkstra, not 
a library call.”
1:15
Show the stats card: walk, bike, car 
ETA
“Same route at 5, 15 and about 30 
km/h: distance divided by speed.”
2:00
Press L, run explain mode once
“These are the first priority-queue 
pops: the node with the smallest 
tentative cost is expanded first.”
2:45
Drop an accident ahead of the walker
“The look-ahead index uses binary 
search over the distance at which the 
route enters each danger zone.”
3:30
Warning 1 at about 500 m, then 
Warning 2
“The weight formula multiplies time by 
one plus lambda times risk, so Dijkstra 
avoids the zone but still finds the 
cheapest safe path.”

Time
Action
What you say
4:30
Press H for the heat-map
“Many accidents on one road make it a 
chronic hot-spot through the 
logarithmic history term.”
5:15
Show the benchmark graph
“Linear is O(n), binary is O(log n); 
measured here on synthetic incidents.”
5:45
State the limits
“Incident data is simulated; OSM 
interior footpaths vary in 
completeness.”
14.1 Likely questions
Question
Short answer
Why write Dijkstra yourself?
So every step can be logged and explained; we also verified it 
against NetworkX.
Why A* as well?
Same optimal result with fewer explored nodes; the 
heuristic is admissible because weights are never below 
distance divided by top speed.
Is this machine learning?
No. The risk score is a transparent formula; that is a 
deliberate design choice for explainability.
Where does the incident data come from?
Simulated for the demo and clearly labelled; the design 
accepts real data through the same table.
What is the complexity?
Dijkstra O((V+E) log V); look-ahead query O(log I + k); 
walker position O(log n) per tick.
Why not Google Maps?
It needs a billing account and cannot be embedded in 
Pygame; OpenStreetMap is free and key-free.
What if no safe route exists?
We fall back to the least-risk path and say so in Warning 2.
How does the walker know it is near danger?
It does not guess: the route polyline is intersected with each 
danger circle ahead of time and the distances are searched 
with bisect.
Why a Pygame window and not Tkinter?
Smooth frame-based animation and state management are 
Pygame’s strengths; Tkinter handles the form-style 
launcher.
What are the limits?
Simulated incidents, OSM coverage gaps, approximate car 
speeds, no live traffic.
15. Risks and Honest Limitations
Risk
Mitigation
OSM interior campus paths may be incomplete
Default demo route uses main roads; coverage warnings in 
the log
contextily needs internet for the first basemap
Run prepare_data.py at home, commit the PNG; road-
only fallback exists
OSMnx function names changed between versions 1.x and 
2.x
Pin osmnx>=2.0 in requirements.txt and test 
imports in Phase 0
nearest_nodes needs scipy (projected graph) or 
scikit-learn (unprojected)
scipy is in requirements.txt
Pygame needs sound device for alerts
Audio failure is caught and logged; visual warnings still 
appear
Examiner asks for real GPS or live traffic
Future scope: phone GPS via a small Flask server; live traffic 
is out of scope for open data
Demo-day laptop differs
Everything is cached; run the scripted demo (F5) on the 

Risk
Mitigation
presentation laptop the day before
16. Suggested Team Split (6 members)
Member
Module
Files
1
Data and graph
graph_loader.py, 
prepare_data.py, 
make_seed_incidents.py
2
Routing algorithms
dijkstra.py, astar.py, 
router.py, test_dijkstra.py
3
Risk and incidents
risk_model.py, incidents.py, 
SQLite, test_risk_model.py
4
Look-ahead and benchmark
lookahead.py, 
search_benchmark.py, 
test_lookahead.py
5
Pygame UI
pygame_app.py, 
map_renderer.py, panel.py, 
audio.py
6
Simulation, logs, launcher
simulation.py, walker.py, 
logger.py, log_console.py, 
launcher.py
17. Dependencies (requirements.txt)
osmnx>=2.0
networkx
numpy
pandas
matplotlib
contextily
shapely
scipy
pygame
plyer
Pillow
pytest
Attribution: the map must show “(c) OpenStreetMap contributors” in the window footer, as 
required by the OpenStreetMap licence.
18. Future Scope
•
Real GPS from a phone browser through a small Flask server (the look-ahead and 
warning logic do not change).
•
Crowdsourced incident reporting form feeding the same SQLite table.
•
Optional hot-spot clustering (DBSCAN) as a clearly separated extra.
•
Web version of the simulation (Leaflet.js) for sharing a link.
•
Mobile port.
