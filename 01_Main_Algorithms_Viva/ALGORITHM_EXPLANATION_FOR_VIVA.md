# SafeRoute — 30-Second Viva Explanation Guide (Main Algorithms)

> **Rule of thumb for every viva answer:** State **what** problem it solves, **what formula/data structure** it uses, **its time complexity**, and **how SafeRoute applies it** — all in under 30 seconds.

---

## 1. Projected Street Graph (`core/graph_loader.py`)
- **What it does:** Downloads and caches OpenStreetMap road networks for three travel modes (`walk`, `bike`, `drive`/`car`) centered on LPU / Chaheru (`31.2551, 75.7035`, 1,500 m radius) into `data/cache/`.
- **Why UTM EPSG:32643:** Raw GPS degrees (`EPSG:4326`) distort distances; projecting to UTM Zone 43N lets every edge length $x, y$ be measured directly in **metres**.
- **Key function:** `snap_to_node(G, lat, lon)` converts WGS84 coordinates with `pyproj.Transformer` and finds the nearest street junction via `ox.nearest_nodes`.

---

## 2. Travel Time Model (`core/travel_model.py`)
- **Constants:** Walk = $1.39\text{ m/s}$ ($5\text{ km/h}$), Bike = $4.17\text{ m/s}$ ($15\text{ km/h}$), Car uses OSM `maxspeed` or highway defaults (`CAR_SPEED_DEFAULTS_KMH`).
- **Base Time:** $t_e = \frac{\text{length}_e}{\text{speed}_e}$ (clamped $\ge 0.1\text{ s}$).

---

## 3. Composite Edge Risk Model (`core/risk_model.py`)
- **Spatial Risk Score (`compute_edge_risk`):** For every road edge geometry $e$ and active danger incident $i$ within radius $R_i$:

$$
r_e = \sum_{d_{ei} \le R_i} s_i \cdot m(\text{type}_i, \text{mode}) \cdot \left(1 - \frac{d_{ei}}{R_i}\right) \cdot e^{-\text{age}_i / 180} \;+\; 0.3 \ln(1 + n_{\text{acc}, e})
$$

  - $s_i$: severity (Accident = 4, Flooding = 4, Unsafe Area = 3, Construction = 2, Road Damage = 2)
  - $m(\text{type}_i, \text{mode})$: sensitivity matrix (e.g., Walkers are more sensitive to `unsafe_area` ($1.2$) than `road_damage` ($0.4$); Cars cannot cross blocking hazards within $40\text{ m}$)
  - $1 - \frac{d_{ei}}{R_i}$: smooth linear distance falloff ($1$ at center $\to 0$ at zone edge)
  - $e^{-\text{age}_i/180}$: exponential decay for historical records ($1.0$ for live hazards)
  - $0.3\ln(1 + n_{\text{acc}, e})$: chronic accident hotspot penalty within $40\text{ m}$

- **Edge Weight Function (`make_weight_fn`):**

$$
w_e =
\begin{cases}
\infty, & \text{if Car mode and blocking hazard } d_{ei} \le 40\text{ m} \\
t_{\text{base}, e} \cdot (1 + \lambda \cdot r_e), & \text{otherwise}
\end{cases}
$$

  If strict blocking disconnects the graph, `fallback=True` switches $\infty$ to a $50\times$ penalty so the least-risk path is still returned.

---

## 4. Dijkstra vs. A\* Pathfinding (`core/dijkstra.py`, `core/astar.py`)
- **Dijkstra:** Expands lowest known cumulative risk-weighted cost $g(n)$ using a binary min-heap (`heapq`) with lazy deletion.
  - Complexity: $O((V + E)\log V)$.
  - MultiDiGraph handling: tracks exact edge key `(u, v, key)` when multiple parallel roads exist between intersections.
- **A\* Search:** Uses $f(n) = g(n) + h(n)$ where heuristic $h(n) = \frac{\sqrt{(x_n - x_{\text{dst}})^2 + (y_n - y_{\text{dst}})^2}}{v_{\max}}$.
  - **Why admissible?** Since Euclidean straight-line distance is never longer than any road path, and edge weights $w_e \ge t_{\text{base}, e} \ge \frac{d_e}{v_{\max}}$, $h(n) \le h^*(n)$ always holds. Therefore **A\* guarantees the exact same optimal cost as Dijkstra while exploring far fewer nodes** (e.g., **10 nodes in 0.17 ms** vs **71 nodes in 1.33 ms** on the LPU campus walk test).

---

## 5. Multi-Criteria Route Options (`core/router.py`)
- `compute_route_alternatives(...)` runs weighted shortest-path search for three risk-aversion weights:
  - **Fastest ($\lambda = 0.0$):** ignores hazard penalties (pure time).
  - **Balanced ($\lambda = 2.0$):** default balanced trade-off between speed and safety.
  - **Safest ($\lambda = 6.0$):** strongly prioritizes long safe detours around danger.
- Duplicate geometries across $\lambda$ values are automatically tagged (`is_duplicate = True`) so the UI only draws distinct dashed alternatives.

---

## 6. Real-Time Look-Ahead & Binary Search (`core/lookahead.py`)
- **`zone_entry_distance`:** Models each hazard as circle $(c_x, c_y, R)$ and solves the quadratic equation $\mathbf{a}t^2 + \mathbf{b}t + \mathbf{c} = 0$ on every polyline segment $P_i \to P_{i+1}$ to compute the exact **metres-along-route entry point** $s_{\text{enter}}$.
- **`build_entry_index` + `query_ahead`:** Sorts live hazard entry distances once into `EntryIndex` ($O(I \log I)$) and queries hazards inside $[s_{\text{now}}, s_{\text{now}} + 500\text{ m}]$ via `bisect.bisect_left` in **$O(\log I)$**.
- **`check_remaining_route_hazard`:** Slices the active polyline directly at the traveller's exact current progress $s_{\text{now}}$ so dropping or dragging a hazard onto the active edge mid-trip triggers immediate rerouting cleanly.
