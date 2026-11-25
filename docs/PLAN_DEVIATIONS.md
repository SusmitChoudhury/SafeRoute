# SafeRoute: Plan Deviations & Design Decisions
**Course:** CSM216 (Python Programming Project)  
**Degree:** B.Tech Computer Science & Engineering, Lovely Professional University  

---

## 1. Executive Summary
Throughout the implementation of SafeRoute (Phases 0 through 8, addressing issues P1–P8), all core algorithmic requirements, mathematical formulas, and viva objectives were strictly preserved. Where minor architectural adaptations were introduced, they were made solely to enhance execution speed, eliminate unnecessary dependencies, comply with the offline university viva environment, and guarantee sub-100 ms real-time performance.

---

## 2. Summary of Deviations and Design Choices

| # | Plan Assumption / Initial Idea | Actual Implementation Decision | Technical Rationale |
|---|---|---|---|
| **D1** | Heavy web framework (Flask / FastAPI) | **Python Standard Library `http.server` (`BaseHTTPRequestHandler`)** | Zero third-party web dependencies. Runs out-of-the-box on any standard Python 3.10+ installation with zero pip install conflicts. |
| **D2** | Drawing straight lines between graph nodes | **Full Edge Geometry Interpolation via `route_to_latlon_polyline`** | (P1) OpenStreetMap curves contain intermediate vertices. Sending the exact road geometry converted via `pyproj` ensures the drawn route line is perfectly coincident with the road and walker (<1 mm error). |
| **D3** | Opening & closing log files on every message | **Line-Buffered Open File Handle (`buffering=1`)** | On Windows NTFS filesystems, repeatedly opening `logs/run_*.log` took 50–60 ms per reroute. Maintaining an open handle reduced logging latency to $<0.05\text{ ms}$, keeping the total reroute pipeline well under the 100 ms budget (actual: ~60 ms). |
| **D4** | Dynamic `LineString` recreation during risk evaluation | **Cached `_cached_geom` on NetworkX edge data dicts** | Eliminates redundant Shapely geometry allocations across 1,584 edges on every tick. |
| **D5** | Repeated risk calculation in candidate alternative routes | **Reusing Precomputed `self.route_risks`** | `compute_route_alternatives` accepts optional `risks` parameter, cutting rerouting runtime by 40 ms. |
| **D6** | Unbounded simulated incidents with large radii (150–200m) | **Sparse Seed Data ($\le 12$ incidents, radius 60–120m, $>100$m from endpoints)** | (P7) Prevents the entire campus map from being covered in red circles at startup, ensures initial route risk is 0.00, and prevents START/GOAL pins from spawning inside hazard zones. |
| **D7** | Google Maps API / Commercial tile services | **100% Free Official OpenStreetMap Standard Tiles & Esri Satellite** | No API keys, no credit cards, zero watermarks, and zero risk of quota expiration during the viva. |
| **D8** | Browser-side route calculations | **Pure Python Brain, Thin Browser Viewer** | All Dijkstra, A*, risk weights, and look-ahead logic execute exclusively in Python. The browser is purely a display layer receiving JSON state. |

---

## 3. Verification & Compliance
Every deviation was verified with automated unit tests in `tests/`:
- **48 automated unit tests passing** across Dijkstra, A*, Look-Ahead, Travel Models, Route Accuracy, REST APIs, Scripted Demo, and Multi-Route Alternatives.
- **Reroute Pipeline execution speed:** 60.2 ms (well under the 100 ms requirement).
- **Polyline accuracy:** $1.16 \times 10^{-9}\text{ m} \ll 1.0\text{ m}$.

