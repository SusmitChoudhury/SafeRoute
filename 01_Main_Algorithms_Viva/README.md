# Part 1: Core Algorithms Showcase (Teacher & Viva Reference)

This folder isolates the **pure algorithmic engine** of **SafeRoute** from the simulation state machine (`sim/`), desktop window (`ui/`), and browser interface (`tools/`), so every algorithm can be inspected, executed, and demonstrated directly during evaluation and viva.

> All files in this folder import directly from `../core/` without modifying any core math or search logic.

---

## Algorithms Covered

| # | Module in `core/` | Algorithm / Model | Time Complexity | Role in SafeRoute |
|---|---|---|---|---|
| 1 | `core/dijkstra.py` | **Dijkstra's Shortest Path** (Min-Heap + Lazy Deletion) | $O((V + E)\log V)$ | Ground-truth optimal safe path & real-time rerouting benchmark |
| 2 | `core/astar.py` | **A\* Heuristic Search** ($h(n) = \frac{\text{Euclidean}(n, \text{goal})}{v_{\max}}$) | $O((V + E)\log V)$ *(fewer nodes)* | Primary fast pathfinder ($1.5\times$–$2\times$ fewer node expansions) |
| 3 | `core/risk_model.py` | **Composite Edge Risk Scoring** ($s \cdot m \cdot f \cdot e^{-\Delta t/180} + \kappa\ln(1+n)$) | $O(E \cdot I)$ | Quantifies spatial proximity, vehicle sensitivity, decay & hotspots |
| 4 | `core/router.py` | **Multi-Criteria Route Optimization** ($\lambda \in \{0, 2, 6\}$) | $3 \times O((V + E)\log V)$ | Generates **Fastest**, **Balanced**, and **Safest** routes simultaneously |
| 5 | `core/lookahead.py` | **Line-Circle Quadratic Entry + `bisect_left`** | $O(V + I\log I)$ build, $O(\log I)$ query | Detects hazards entering the 500 m look-ahead horizon in real time |

---

## Core Weight Formula

Every edge $e = (u, v, k)$ on the OpenStreetMap UTM-projected road graph is weighted in **risk-adjusted travel seconds**:

$$
w_e =
\begin{cases}
\infty, & \text{if } \text{mode} = \text{car} \text{ and blocking incident distance } d_{ei} \le 40\text{ m} \\
t_{\text{base}, e} \cdot \left(1 + \lambda \cdot r_e\right), & \text{otherwise}
\end{cases}
$$

Where the composite risk $r_e$ combines linear distance falloff $f = \max\left(0, 1 - \frac{d_{ei}}{R_i}\right)$, severity $s_i$, travel-mode sensitivity $m(\text{type}_i, \text{mode})$, exponential historical age decay $e^{-\text{age}_i / 180}$, and logarithmic accident hotspot density $\kappa \ln(1 + n_{\text{acc}, e})$.

---

## Run Standalone Core Algorithm Demo

From the repository root:

```bash
python 01_Main_Algorithms_Viva/run_core_algorithms_demo.py
```

This runs end-to-end verification in seconds with clear formatted output for:
1. Loading the LPU campus OpenStreetMap graph (`core/graph_loader.py`)
2. Running & comparing **Dijkstra vs. A\*** optimality and node expansions
3. Dropping a simulated hazard and showing **Multi-Criteria Route Alternatives** ($\lambda = 0, 2, 6$)
4. Building the **Quadratic Entry Index** and running **Binary Search (`bisect_left`)** look-ahead queries
5. Printing runtime comparison across **Walk / Bike / Car** modes (`core/router.py`).
