"""
tools/viva_quiz.py – Interactive Viva Revision Quiz for SafeRoute (CSM216).

Lets the student practice essential viva questions directly from the terminal.
Usage:
    python tools/viva_quiz.py
"""

import sys
import random

QUESTIONS = [
    {
        "q": "Why did we write Dijkstra and A* ourselves instead of calling networkx.shortest_path?",
        "options": [
            "A) NetworkX is too slow for simple road graphs",
            "B) To instrument node explorations, relaxations, live explain mode, and dynamic risk weights for academic evaluation",
            "C) NetworkX cannot load OpenStreetMap files",
            "D) Python standard library does not support graph packages"
        ],
        "answer": "B",
        "explanation": "In course CSM216, the educational goal is algorithmic mastery. We wrote our own priority queue using heapq to log every relaxation, provide Explain Mode (L), and dynamically scale edge weights by risk."
    },
    {
        "q": "What is the A* heuristic function used in SafeRoute, and why is it admissible?",
        "options": [
            "A) Manhattan distance / average speed",
            "B) Euclidean distance / v_max, because straight-line distance divided by top speed never overestimates actual travel time",
            "C) Dijkstra shortest path distance",
            "D) Total road edge count multiplied by base time"
        ],
        "answer": "B",
        "explanation": "Euclidean distance is the shortest possible path between two points. Dividing by the maximum possible speed v_max guarantees h(n) <= h*(n) (admissibility), ensuring optimal solutions."
    },
    {
        "q": "Which coordinate reference system (CRS) is used for routing calculations and distance metrics?",
        "options": [
            "A) WGS84 Degrees (EPSG:4326)",
            "B) Web Mercator (EPSG:3857)",
            "C) UTM Zone 43N (EPSG:32643) in physical metres",
            "D) Screen pixel coordinates"
        ],
        "answer": "C",
        "explanation": "UTM Zone 43N represents coordinates in true Euclidean metres with <0.04% distortion at LPU's latitude, unlike degrees where longitude shrinks with cos(latitude)."
    },
    {
        "q": "How does SafeRoute's look-ahead system detect danger zones ahead of the traveller?",
        "options": [
            "A) Repeated brute-force pairwise distance checks every frame",
            "B) Quadratic line-circle intersection precomputed into a sorted 1D array, queried via bisect_left in O(log I + k) time",
            "C) Google Maps Geofencing API",
            "D) Checking bounding boxes of the entire city"
        ],
        "answer": "B",
        "explanation": "The road polyline is intersected with incident circles using quadratic equations. Entry milestones are stored in a sorted array and queried with binary search in O(log I + k) time."
    },
    {
        "q": "What are the three route alternatives computed in compute_route_alternatives?",
        "options": [
            "A) Walk, Bike, Car",
            "B) Fastest (lambda=0), Balanced (lambda=2), Safest (lambda=6)",
            "C) Highway, Boulevard, Footpath",
            "D) Shortest, Longest, Scenic"
        ],
        "answer": "B",
        "explanation": "Fastest ignores risk (lambda=0), Balanced trades off time vs risk (lambda=2, default), and Safest maximizes risk aversion (lambda=6)."
    },
    {
        "q": "What is the time complexity of the look-ahead query?",
        "options": [
            "A) O(n^2)",
            "B) O(I * E)",
            "C) O(log I + k) where I is total incidents and k is active alerts in the horizon",
            "D) O(1) constant time hashmap lookup"
        ],
        "answer": "C",
        "explanation": "Binary search (bisect_left) locates the current position in log(I) time, then linearly yields the k entries within the horizon window."
    },
    {
        "q": "What is the relationship between the Pygame window and the Web UI at localhost:8000?",
        "options": [
            "A) They run completely separate routing engines and separate algorithms",
            "B) They are two thin viewers of the exact same Python simulation engine (sim/simulation.py)",
            "C) Pygame is frontend only, and the Web UI is a mockup",
            "D) The Web UI connects to a remote Google Cloud server"
        ],
        "answer": "B",
        "explanation": "Two viewers of one engine. Python core/ and sim/ run all algorithms, state machines, and physics; Pygame renders SDL desktop graphics, while web_server.py streams JSON to Leaflet."
    },
    {
        "q": "Why is there no Machine Learning in the hazard risk model?",
        "options": [
            "A) Python cannot run machine learning libraries",
            "B) Neural networks require GPUs which we didn't have",
            "C) For academic explainability and safety: our rule-based formula is 100% mathematically transparent and auditable in a viva",
            "D) Machine learning algorithms cannot output numbers between 0 and 1"
        ],
        "answer": "C",
        "explanation": "Viva evaluation requires complete transparency. If an edge cost triples, the student can point to the exact severity, spatial distance, and mode multiplier that caused it."
    },
    {
        "q": "What happens when an incident is dragged and dropped on the road while the simulation is running?",
        "options": [
            "A) The page freezes and restarts from the beginning",
            "B) The server executes the 6-step reroute pipeline in <100 ms, splicing a dynamic detour from the next junction ahead",
            "C) The walker stops and waits for user confirmation",
            "D) It only updates the visual circle without recalculating the route"
        ],
        "answer": "B",
        "explanation": "The 6-step pipeline (Detect -> Weights -> Search -> Options -> Compare -> Switch) executes in 30-60 ms, seamlessly diverting the walker without pausing."
    },
    {
        "q": "How does SafeRoute handle the situation where all roads are blocked by severe hazards?",
        "options": [
            "A) Crashes with an unhandled ZeroDivisionError",
            "B) Halts and displays an infinite loop warning",
            "C) Applies a finite penalty fallback (fallback=True) to find the least hazardous passable route",
            "D) Deletes all hazards automatically"
        ],
        "answer": "C",
        "explanation": "Instead of crashing or getting stuck, the router applies a finite fallback penalty to guide the traveller along the least dangerous path."
    }
]


def run_quiz():
    print("\n" + "=" * 65)
    print("   SafeRoute (CSM216) – Interactive Viva Revision Quiz")
    print("   Test your conceptual & algorithmic mastery in 10 questions!")
    print("=" * 65 + "\n")

    score = 0
    shuffled = list(QUESTIONS)
    random.shuffle(shuffled)

    for idx, item in enumerate(shuffled, 1):
        print(f"\n[Question {idx}/10] {item['q']}\n")
        for opt in item["options"]:
            print(f"   {opt}")

        user_ans = input("\nYour answer (A/B/C/D): ").strip().upper()
        if user_ans == item["answer"]:
            score += 1
            print(f"\n Correct! (+1)")
        else:
            print(f"\n Incorrect. Correct answer was [{item['answer']}].")

        print(f"Explanation: {item['explanation']}\n" + "-" * 60)

    print("\n" + "=" * 65)
    print(f"Quiz Finished! Final Score: {score} / 10 ({score * 10}%)")
    if score >= 9:
        print("Outstanding! You are fully prepared to score an A+ in your viva!")
    elif score >= 7:
        print("Great performance! Review docs/VIVA_NOTES.md to polish the finer details.")
    else:
        print("Keep practicing! Read docs/VIVA_QUESTIONS.md to master every concept.")
    print("=" * 65 + "\n")


if __name__ == "__main__":
    run_quiz()

