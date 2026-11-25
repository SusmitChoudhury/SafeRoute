# SafeRoute: Viva Preparation Guide & Project Notes
**Course:** CSM216 (Python Project)  
**Degree:** B.Tech Computer Science & Engineering, Lovely Professional University  
**Topic:** Real-Time Hazard-Aware Multi-Modal Route Simulator  
**Location:** LPU Campus / Chiheru Street Network (Punjab, India)  

---

## 1. Project Overview & Elevator Pitch

> *"SafeRoute is a desktop simulator where a walker, cyclist, or driver navigates the real OpenStreetMap road network of LPU and Chiheru. Users can dynamically place accidents, waterlogging, or construction zones on the map. When a danger zone enters within 500 metres ahead of the traveller, the system raises Warning 1, calculates a dynamic risk-weighted detour using our own A\* search, and displays Warning 2 with the extra distance and time incurred. Every step of the algorithm is logged live in an explainable side panel."*

---

## 2. Architecture & Module-by-Module Breakdown

```
SafeRoute/
├── config.py                 # Single source of truth for all tunable constants
├── core/                     # Pure algorithmic core (NO Pygame / Tkinter dependencies)
│   ├── graph_loader.py       # Loads cached OSM MultiDiGraph in projected UTM CRS
│   ├── dijkstra.py           # Custom Dijkstra with heapq, MultiDiGraph, & explain trace
│   ├── astar.py              # Custom A* with admissible Euclidean distance heuristic
│   ├── risk_model.py         # Rule-based hazard risk formula & dynamic edge weighting
│   ├── travel_model.py       # Speed assignments & multi-modal ETA comparisons
│   ├── lookahead.py          # Line-circle intersection & O(log I + k) binary search index
│   ├── router.py             # Route computation, next-junction splicing, & delta metrics
│   └── search_benchmark.py   # Empirical benchmark: linear vs binary, Dijkstra vs A*
├── sim/                      # Simulation engine & state management
│   ├── simulation.py         # Detect-and-reroute state machine & tick loop
│   ├── walker.py             # Traveller motion using O(log n) segment bisect
│   ├── incidents.py          # SQLite database storage (db/saferoute.db)
│   ├── scripted_demo.py      # Seed 42 deterministic viva scenario (F5 key)
│   └── logger.py             # 500-line ring buffer & logs/run_<timestamp>.log sink
├── ui/                       # Visual presentation layer
│   ├── launcher.py           # Tkinter setup window (mode, speed, features)
│   ├── pygame_app.py         # 60 FPS Pygame loop and keyboard/mouse event dispatcher
│   ├── map_renderer.py       # 1:1 vector-to-raster coordinate projection renderer
│   ├── panel.py              # Route stats card, mode comparisons, & warning banners
│   ├── log_console.py        # Syntax-colored scrolling algorithm terminal
│   └── audio.py              # Synthesized dual-tone warning sound effects
├── tools/                    # One-time data preparation scripts
│   ├── prepare_data.py       # Downloads OSM data, stitches basemap tiles, projects CRS
│   ├── make_seed_incidents.py# Generates realistic historical seed incident dataset
│   └── view_static_map.py    # Offline visual alignment validation
└── tests/                    # Comprehensive automated pytest test suite (35+ tests)
```

---

## 3. Core Mathematical Formulas & Algorithms

### 3.1 Transparent Rule-Based Hazard Risk (Section 6.4)
We deliberately chose **not** to use a black-box Machine Learning model so every number is explainable in an academic viva:
$$\text{risk}(e) = \sum_{i \in \text{hazards}} \left[ s_i \cdot m_{\text{type}} \cdot f(d) \cdot e^{-\frac{\text{age}}{180}} \right] + \kappa \cdot \ln(1 + \text{accidents}_e)$$

- **Severity ($s_i \in [1, 5]$):** Inherent danger rating of the incident.
- **Mode Multiplier ($m_{\text{type}}$):**
  - Walking near flooding: $m = 0.5$ (can wade or step around).
  - Driving through flooding: $m = 1.5$ (engine hydrolock risk).
  - Walking in unsafe area at night: $m = 1.5$.
- **Linear Spatial Falloff ($f(d)$):**
  $$f(d) = \max\left(0, 1 - \frac{d}{R}\right)$$
  Equals $1.0$ at the hazard centre and drops linearly to $0.0$ at the perimeter radius $R$.
- **Exponential Time Decay:** $e^{-\text{age}/180}$ reduces historical impact with a half-life of ~180 days.
- **Chronic Accident History:** $\kappa \cdot \ln(1 + \text{count})$ penalizes known dangerous road corridors without letting outliers explode.

### 3.2 Dynamic Edge Weight Function
$$w(e) = \text{base\_time}(e) \cdot (1 + \lambda \cdot \text{risk}(e))$$
- With $\lambda = 2.0$, a road with risk $1.0$ triples its traversal penalty in Dijkstra/A\*, prompting the algorithm to find a safe detour if one exists.
- **Physical Vehicle Blocking:** Cars cannot drive through severe accidents or construction ($d \le 40\text{ m} \implies w(e) = \infty$). Walkers can still pass with elevated risk penalty.
- **Disconnected Fallback:** If all roads are blocked, the router applies a finite $50\times$ penalty rather than crashing with an unhandled exception.

### 3.3 Admissible A\* Heuristic
$$h(n) = \frac{\text{EuclideanDistance}(n, \text{destination})}{v_{\max}}$$
- Since Euclidean distance is the shortest possible path between two points and $v_{\max}$ is the top speed allowed in that mode, $h(n) \le h^*(n)$ always holds true.
- **Guarantee:** Because the heuristic never overestimates the true remaining travel time (admissibility), A\* is mathematically guaranteed to return the exact same optimal cost as Dijkstra, while exploring **35% to 55% fewer nodes**.

### 3.4 Look-Ahead Detection (Line-Circle Quadratic Intersection)
To detect danger zones along curved roads without approximating them as points:
For each road segment from $A$ to $B$ and incident circle centre $c$ with radius $R$:
$$\|A + u(B - A) - c\|^2 = R^2 \quad \text{for } u \in [0, 1]$$
Solving the quadratic equation $a u^2 + b u + c = 0$ yields the exact entry distance:
$$s_{\text{enter}} = D_A + u \cdot \|B - A\|$$
- All entry points along the planned route are stored in a sorted array `entry_keys`.
- At each tick, when the traveller is at distance $s_{\text{now}}$, the look-ahead query executes:
  ```python
  lo = bisect_left(entry_keys, s_now)
  while lo < len(entry_keys) and entry_keys[lo] <= s_now + 500.0:
      hits.append(entry_ids[lo])
      lo += 1
  ```
- **Query Complexity:** $O(\log I + k)$ compared to $O(I)$ for a linear scan.

---

## 4. Key Questions & Viva Answers

### Q1: Why did you write Dijkstra and A\* yourselves instead of calling `networkx.shortest_path`?
> **Answer:** In course CSM216, the learning goal is algorithmic understanding. By implementing our own priority queue using Python's standard `heapq`, we can instrument every single relaxation, log the exact node expansions, and provide an interactive **Explain Mode (Key L)** that outputs the priority queue trace live. Furthermore, standard library implementations do not natively handle multi-attribute dynamic risk scaling across multi-directed graphs (`MultiDiGraph`). We used NetworkX solely to load the OSM graph and as an independent unit-test oracle to verify our algorithm across 100 random pairs.

### Q2: Why both Dijkstra and A\*? What is the difference?
> **Answer:** Dijkstra is an uninformed search that expands outward uniformly in all directions ($h(n) = 0$). A\* incorporates a goal-directed heuristic $h(n) = \text{dist}/v_{\max}$. In our empirical benchmarks (`docs/benchmark_dijkstra_astar.png`), both algorithms produce the exact same route cost down to $10^{-6}$, but A\* explores **~38% to 55% fewer nodes** and executes significantly faster.

### Q3: Why is there no Machine Learning in the risk model?
> **Answer:** High-stakes routing and emergency navigation require deterministic, auditable decisions. Neural networks can hallucinate or fail silently under out-of-distribution inputs. Our rule-based formula provides complete mathematical transparency: if an edge weight increases, we can point to the exact incident severity, spatial distance, mode multiplier, and age decay that caused it.

### Q4: Why are all distances computed in UTM (EPSG:32643) instead of degrees or Web Mercator?
> **Answer:** Degrees (WGS84 EPSG:4326) cannot be used directly with the Euclidean metric because $1^\circ$ of longitude shrinks as latitude moves away from the equator ($\Delta x = \Delta \text{lon} \cdot \cos(\text{lat})$). Web Mercator (EPSG:3857) distorts ground scale by $1/\cos(\text{lat})$ (~17% error at LPU's latitude of $31.25^\circ$). We project all coordinates to **UTM Zone 43N (EPSG:32643)**, where coordinates represent true physical metres with distortion under 0.04%. We convert to screen pixels only at the final rendering stage.

### Q5: What is the computational complexity of the project?
- **Dijkstra:** $O((V + E) \log V)$ using a binary min-heap (`heapq`).
- **A\* Search:** $O((V + E) \log V)$ worst case, with substantially smaller average branching factor.
- **Look-Ahead Query:** $O(\log I + k)$ via `bisect_left` over sorted corridor hazards, where $I$ is the number of incidents and $k$ is the number of active alerts within the 500 m window.
- **Walker Animation:** $O(\log S)$ per tick using binary search on cumulative polyline distances.

### Q6: What are the known limitations of the simulator?
1. **Simulated Incidents:** In the absence of an open real-time municipal traffic incident feed for Chiheru/Phagwara, hazard data is generated synthetically and seeded for reproducibility (`seed=42`).
2. **Pedestrian Connectivity:** OpenStreetMap interior campus footpaths occasionally lack full topological connectivity to the exterior vehicular network; we handle this with snapped endpoints and fallback penalties.

---

## 5. Viva Demonstration Script (6-Minute Walkthrough)

| Elapsed | Action / Key | What to Say / Point Out |
|---|---|---|
| **0:00** | Run `python main.py`<br>Select `Walk`, Speed `x10`, Click **Start** | *"This is our SafeRoute desktop simulator for CSM216. It runs on the real OpenStreetMap road network of the LPU and Chiheru area, completely offline from local cache."* |
| **0:45** | Point to **Live Log Console** on the right side panel | *"Notice the live log: every number is calculated live by our own Dijkstra and A\* implementation. It prints the number of explored nodes, relaxations, and millisecond runtimes."* |
| **1:30** | Point to the **Stats Card** | *"Here is the multi-modal travel time comparison: our engine computes the same route for Walking (5 km/h), Biking (15 km/h), and Driving (OSM road maxspeeds)."* |
| **2:15** | Press **L** (Explain Mode) | *"Pressing L activates Explain Mode. The log immediately traces the priority queue pops, showing which node was expanded with the smallest tentative cost."* |
| **3:00** | **Left-Click** to drop an Accident ahead of the walker | *"I am dropping an accident along the planned corridor. The look-ahead system uses binary search over our pre-computed polyline entry index."* |
| **3:45** | Observe **Warning 1** & **Warning 2** | *"When the hazard comes within 500 metres, Warning 1 triggers with an audible alarm. The engine immediately splices a dynamic detour from the next junction ahead, and Warning 2 shows the extra distance (+m) and time (+min)."* |
| **4:30** | Press **H** (Risk Heat-Map) | *"Pressing H toggles the network risk heat-map, highlighting historical accident blackspots through our logarithmic history term."* |
| **5:15** | Open `docs/benchmark_search.png` & `docs/benchmark_dijkstra_astar.png` | *"Here are our empirical benchmarks: linear search takes 22 ms at 100k incidents while binary search takes 12 microseconds (1780x faster). A\* saves ~38% of node expansions over Dijkstra."* |
| **5:45** | Press **F5** | *"Pressing F5 runs the fully deterministic scripted demo with seed 42 to reproduce the entire sequence from start to destination arrival."* |

---

## 6. Two Viewers of One Engine (Explainable in 15 Seconds)
> *"Pygame and the Web UI are two thin viewers of the exact same Python simulation engine (`sim/simulation.py`). All routing algorithms, risk formulas, look-ahead binary search, and state transitions execute in pure Python. The Pygame desktop window renders native SDL 2D graphics for offline demonstrations, while the Web interface streams JSON state via standard library HTTP to an OpenStreetMap Leaflet client with interactive HTML5 drag-and-drop."*

---

## 7. The 6-Step Reroute Pipeline (Explainable in 30 Seconds)
When a hazard is dropped or entered ahead on the road, SafeRoute executes a deterministic 6-step pipeline in **< 100 ms** (typically 30–60 ms):
1. **STEP 1/6 Detect:** The $O(\log I + k)$ binary search index checks if any active hazard circle intersects the remaining route polyline (either instantly or within the 500 m horizon).
2. **STEP 2/6 Weights:** For every road edge within the hazard's influence, edge risk is updated via our transparent formula: $\text{risk}(e) = \sum s_i \cdot m_{\text{type}} \cdot (1 - d/R) \cdot e^{-\text{age}/180}$. Edge weight becomes $w = t \cdot (1 + \lambda \cdot r)$.
3. **STEP 3/6 Search:** Dijkstra runs from `walker.next_node_ahead` to the goal node, exploring only the remaining graph.
4. **STEP 4/6 Options:** The engine computes three candidate routes using identical Dijkstra search with varying risk aversion ($\lambda=0$ Fastest, $\lambda=2$ Balanced, $\lambda=6$ Safest), deduplicating identical paths.
5. **STEP 5/6 Compare:** Evaluates old vs. new path deltas: extra distance ($+\Delta \text{ m}$), extra time ($+\Delta \text{ min}$), and risk reduction ($r_{\text{old}} \to r_{\text{new}}$).
6. **STEP 6/6 Switch:** Splices the already-travelled prefix with the new detour path. The walker transitions seamlessly without teleporting or stopping.
7. **DONE Shortcut Check:** Audits if a shorter road exists, logging whether it is open or blocked by higher hazard risks.

---

## 8. The 3 Route Options (&lambda; Risk Aversion)
- **⚡ Fastest ($\lambda = 0.0$):** Minimizes purely travel time, ignoring danger zones.
- **⚖️ Balanced ($\lambda = 2.0$, Default):** Pragmatic trade-off. A hazard with risk 1.0 triples the road traversal penalty, prompting a detour if a reasonable safe alternative exists.
- **🛡️ Safest ($\lambda = 6.0$):** Aggressive risk aversion. Severely penalizes any road segment touching even minor hazards, choosing wide detours through quiet back roads.

