# SafeRoute: 40 Viva Questions & Answers
**Course:** CSM216 (Python Programming Project)  
**Degree:** B.Tech Computer Science & Engineering, Lovely Professional University  
**Project:** SafeRoute – Real-Time Hazard-Aware Route Simulator  

---

### Section A: Algorithmic Foundations (Dijkstra & A*)

#### Q1. Why did you implement Dijkstra and A* yourselves rather than using NetworkX?
**Answer:** NetworkX is a general graph library, but in CSM216 our learning goal is algorithm design and complexity analysis. Writing our own priority queue with Python’s `heapq` allows us to instrument node explorations, record exact relaxation counts, create a live explain-mode trace, and handle dynamic multi-attribute risk-penalized edge weights. We only use NetworkX to load the OSM graph and as an automated testing oracle across 100 test pairs.

#### Q2. What is the difference between Dijkstra and A*?
**Answer:** Dijkstra is an uninformed search that explores outward equally in all directions ($h(n) = 0$). A* is a goal-directed search using an evaluation function $f(n) = g(n) + h(n)$, where $g(n)$ is the exact cost from the start and $h(n)$ is an admissible heuristic estimating cost to destination.

#### Q3. What is your A* heuristic function, and why is it admissible?
**Answer:** Our heuristic is $h(n) = \frac{\text{EuclideanDistance}(n, \text{destination})}{v_{\max}}$. Euclidean straight-line distance is the shortest possible path in 2D space, and dividing by maximum legal speed $v_{\max}$ yields the minimum possible time. Because it never overestimates true travel time ($h(n) \le h^*(n)$), it is admissible and mathematically guaranteed to return the exact same optimal cost as Dijkstra.

#### Q4. What time complexity does your Dijkstra search achieve?
**Answer:** $O((V + E) \log V)$ using a binary min-heap (`heapq`). For our LPU-Chiheru road graph with ~650 nodes and ~1,580 edges, Dijkstra executes in 1 to 4 milliseconds.

#### Q5. What happens if a node is visited multiple times with different tentative costs in `heapq`?
**Answer:** Python’s `heapq` does not support `decrease-key` efficiently. We use the standard "lazy deletion" pattern: we push a new `(new_cost, node)` entry into the heap whenever a shorter path is found. When popping `(cost, u)`, if `cost > dist[u]`, it is stale and immediately discarded.

#### Q6. What are the three candidate routes computed by `compute_route_alternatives`?
**Answer:** They use the same Dijkstra algorithm with three risk aversion factors:
1. **Fastest ($\lambda = 0.0$):** Pure travel time, ignores danger.
2. **Balanced ($\lambda = 2.0$, default):** Reasonable trade-off between detour length and hazard avoidance.
3. **Safest ($\lambda = 6.0$):** High hazard penalty, detours through calm back paths.

#### Q7. How does the system handle identical candidate routes?
**Answer:** If two lambda values produce the exact same sequence of road nodes, the router tags the duplicate with `is_duplicate = True` and sets `duplicate_of = "fastest"` so the UI doesn’t draw overlapping lines or confuse the user.

#### Q8. What is the shortcut check after a reroute?
**Answer:** The router audits whether a shorter route exists. If Fastest has lower travel time than Balanced, it logs: *"No shorter alternative exists, or shortest road is not used because of risk X (+Y min)"*, ensuring complete viva transparency.

#### Q9. How do you prevent graph disconnection when all roads are blocked?
**Answer:** We implement a graceful penalty fallback (`fallback=True`). If $w(e) = \infty$ for all paths, the router falls back to a finite $50\times$ penalty instead of throwing an unhandled exception or leaving the traveler stranded.

#### Q10. How do you ensure the route line on the map exactly matches the walker's path?
**Answer:** We vector-transform every intermediate vertex along the OpenStreetMap edge geometry (`geometry` attribute of OSM edges) using `pyproj.Transformer` from UTM Zone 43N metres to WGS84 lat/lon. We never draw straight lines between junctions only.

---

### Section B: Mathematics & Risk Model

#### Q11. Explain your hazard risk formula.
**Answer:**
$$\text{risk}(e) = \sum_{i \in \text{hazards}} \left[ s_i \cdot m_{\text{type}} \cdot \max\left(0, 1 - \frac{d}{R}\right) \cdot e^{-\frac{\text{age}}{180}} \right] + \kappa \cdot \ln(1 + \text{accidents}_e)$$
It combines severity, mode multiplier, linear spatial distance falloff, exponential time decay (180-day half-life), and logarithmic chronic accident history.

#### Q12. Why linear spatial falloff $1 - d/R$?
**Answer:** It equals $1.0$ at the exact incident center, drops linearly to $0.0$ at perimeter radius $R$, and stays zero beyond $R$. It is smooth, continuous, and computationally fast without square roots.

#### Q13. Why use a logarithmic term $\kappa \cdot \ln(1 + \text{accidents})$ for chronic history?
**Answer:** Logarithmic scaling penalizes recurrent blackspots (e.g. 3 accidents on a highway segment) without letting high accident counts explode the edge cost exponentially. The $+1$ ensures $\ln(1) = 0$ when an edge has zero prior accidents.

#### Q14. What are the mode multipliers ($m_{\text{type}}$) and why do they differ?
**Answer:** Physical vulnerability varies by vehicle:
- Walkers can walk around waterlogging ($m=0.5$), but cars face engine flooding ($m=1.5$).
- Walkers avoid unlit unsafe areas ($m=1.5$), while cars pass safely through them ($m=0.5$).

#### Q15. How does risk modify travel time into edge weight?
**Answer:**
$$w(e) = t_e \cdot (1 + \lambda \cdot \text{risk}(e))$$
With $\lambda = 2.0$, a road with risk $1.0$ takes 3 times as long in Dijkstra’s priority queue, favoring clean detours.

#### Q16. What is the physical blocking rule for motor vehicles?
**Answer:** When travel mode is Car, any severe accident ($s \ge 4$) or road construction within 40 metres sets $w(e) = \infty$, representing physical road blockage. Walkers can still squeeze past with high risk.

#### Q17. Why is there no Machine Learning in the risk model?
**Answer:** Explainability. In viva evaluation and emergency planning, every detour must be mathematically auditable. Neural networks can hallucinate or fail unpredictably; our formula lets a student explain any edge weight in 15 seconds.

#### Q18. What coordinate system is used for physics and routing, and why?
**Answer:** Universal Transverse Mercator (UTM Zone 43N, EPSG:32643). UTM coordinates are in physical metres with $<0.04\%$ distortion at LPU's latitude, unlike degrees (EPSG:4326) which distort longitude distance by $\cos(31.25^\circ) \approx 0.855$.

#### Q19. How do you convert coordinates between UTM and latitude/longitude?
**Answer:** We use `pyproj.Transformer.from_crs("EPSG:32643", "EPSG:4326", always_xy=True)` with vectorized array transformation for sub-millisecond execution.

#### Q20. What is the speed assignment for each travel mode?
**Answer:**
- Walk: $5.0\text{ km/h}$ ($1.39\text{ m/s}$)
- Bike: $15.0\text{ km/h}$ ($4.17\text{ m/s}$)
- Car: OpenStreetMap `maxspeed` tag parsed into m/s, defaulting to $35.0\text{ km/h}$ on unclassified campus roads.

---

### Section C: Real-Time Simulation & Look-Ahead

#### Q21. How does the look-ahead detection system work?
**Answer:** We model road segments as line segments and hazards as circles. By solving the quadratic equation $\|A + u(B - A) - c\|^2 = R^2$, we calculate the exact distance $s_{\text{enter}}$ along the route where the road enters each hazard.

#### Q22. What data structure powers look-ahead queries, and what is its complexity?
**Answer:** A sorted 1D array of entry distance milestones (`entry_keys`) with parallel incident IDs (`entry_ids`). Querying entries ahead uses binary search (`bisect_left`) with complexity $O(\log I + k)$, where $I$ is total incidents and $k$ is active alerts within the look-ahead horizon.

#### Q23. What is the difference between "Instant" and "500m" detection modes?
**Answer:**
- **Instant (Default):** Evaluates hazards across the entire remaining route. As soon as a danger touches any future segment, it reroutes immediately.
- **500m Lookahead:** Only warns and reroutes when the danger is within 500 metres ahead of the traveller’s current position.

#### Q24. Walk through the 6-step reroute pipeline.
**Answer:**
1. **Detect:** Binary search finds intersecting hazard.
2. **Weights:** Formula updates edge risks for affected roads.
3. **Search:** Dijkstra re-runs from next road junction.
4. **Options:** Calculates Fastest, Balanced, Safest alternatives.
5. **Compare:** Calculates $+\Delta \text{ m}$, $+\Delta \text{ min}$, and risk delta.
6. **Switch:** Splices historical route with new detour; walker continues smoothly.

#### Q25. What is the execution time budget for the reroute pipeline?
**Answer:** The budget is under 100 milliseconds. SafeRoute finishes all 6 steps in **30 to 60 ms** on standard laptop CPUs.

#### Q26. How does the walker move between vertices on curved roads?
**Answer:** The walker tracks distance travelled $s$. Using binary search (`bisect_right`) over the cumulative segment distance array, it finds the active edge segment $[D_i, D_{i+1}]$ and interpolates position $P = P_i + \frac{s - D_i}{D_{i+1} - D_i}(P_{i+1} - P_i)$ in $O(\log S)$ time.

#### Q27. What happens when a hazard is dragged while the simulation is running?
**Answer:** During mouse drag, the hazard circle follows the cursor locally without server computation. On mouse release, the client sends `POST /api/move_incident`, which updates SQLite, rebuilds the look-ahead index, and triggers the 6-step reroute pipeline in $<60\text{ ms}$.

#### Q28. What are the simulation states in `SimState`?
**Answer:**
- `IDLE`: Loaded at start, awaiting play.
- `MOVING`: Traveller advancing along route.
- `WARNING_1`: Danger detected ahead; audio alert and pipeline triggered.
- `WARNING_2`: Safe detour calculated; green success banner showing $+\Delta \text{ m}$ and $+\Delta \text{ min}$.
- `ARRIVED`: Traveller reached destination node; final metrics logged.

#### Q29. What happens if the user drags START or GOAL into an active danger zone?
**Answer:** The server checks Euclidean distance to all active hazard centers; if distance $\le$ radius, it logs a prominent warning: `WARN endpoint GOAL marker placed inside danger zone #X!`.

#### Q30. Why is the scripted demo deterministic (Seed 42)?
**Answer:** `random.seed(42)` and `np.random.seed(42)` ensure identical initial hazards, identical walker movement ticks, and identical rerouting events on every demo run (triggered by <kbd>F5</kbd>).

---

### Section D: Software Architecture & Web Interface

#### Q31. What is the relationship between Pygame and the Web UI?
**Answer:** They are two lightweight viewers of the same Python engine (`sim/simulation.py`). The core algorithms, risk model, and state machine reside in `core/` and `sim/`. Pygame renders via SDL, while the Web server streams JSON state to Leaflet.

#### Q32. What web framework is used for localhost:8000?
**Answer:** Python’s built-in standard library `http.server` (`BaseHTTPRequestHandler`) with a custom multi-threaded host (`threading.Thread`). No heavy external frameworks (Flask/Django/FastAPI) are required.

#### Q33. Why do you use official OpenStreetMap tiles instead of Google Maps API?
**Answer:** Official OpenStreetMap standard tiles and Esri World Imagery satellite tiles are 100% free, require zero API keys, never display watermarks, and adhere strictly to open academic licensing.

#### Q34. How is OpenStreetMap attribution displayed?
**Answer:** A styled semi-transparent glass badge floating at `bottom: 84px; left: 16px;` above the dock toolbar, displaying `© OpenStreetMap contributors | SafeRoute Project CSM216` as legally required by the ODbL license.

#### Q35. How does the frontend communicate with Python?
**Answer:** Polling every 120 ms (~8 Hz) via `fetch('/api/state')` for smooth 60 FPS interpolation, with immediate `POST` calls for user actions like `select_route`, `set_endpoint`, and `drop_incident`.

#### Q36. Where are incidents stored persistently?
**Answer:** In a local SQLite database (`db/saferoute.db`) with columns for `id`, `type`, `lat`, `lon`, `severity`, `radius_m`, `blocking`, `source` (`historical` vs `live`), and `active`.

#### Q37. How are historical seed incidents distinguished from live hazards?
**Answer:**
- **Historical (Simulated):** Drawn as dashed lighter circles with `fillOpacity: 0.18` and labeled `simulated`.
- **Live Hazards:** Drawn with solid glowing borders (`weight: 2.5`), brighter fill, and labeled `live`.

#### Q38. How is log output managed in memory and on disk?
**Answer:** `sim/logger.py` maintains an in-memory `collections.deque` ring buffer of the last 500 lines for the UI terminal, and concurrently streams to a line-buffered (`buffering=1`) file sink in `logs/run_<timestamp>.log`.

#### Q39. How many automated tests exist, and how are they run?
**Answer:** 48 passing automated tests in `tests/`, covering Dijkstra optimality, A* heuristic admissibility, 1-meter polyline precision, drag-and-drop REST endpoints, 6-step reroute timing, and deterministic F5 reproduction. Run with `pytest`.

#### Q40. If you had another month, what future enhancement would you prioritize?
**Answer:** Incorporating elevation contours from SRTM DEM data for grade-aware cycling impedance, and connecting live weather radar GeoJSON feeds for real-time monsoon waterlogging detection across Punjab state highways.

