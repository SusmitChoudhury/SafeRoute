"""
ui/launcher.py – Tkinter start and setup window.

Implements Syllabus Unit 2 requirements:
  - Tkinter widgets: Label, Radiobutton, Combobox, Checkbutton, Button.
  - Geometry manager: grid() layout with clean padding and styling.
  - Event binding: Start button and Escape key bindings.

Allows the user to select travel mode, simulation speed scale, and demo scenario
before launching the Pygame simulation.
"""

import tkinter as tk
from tkinter import ttk
from typing import Optional


def run_launcher() -> Optional[dict]:
    """Display the Tkinter setup launcher window.

    Returns:
        dict | None: Selected configuration dictionary, or None if closed.
    """
    settings: Optional[dict] = None

    root = tk.Tk()
    root.title("SafeRoute – Setup & Launcher (CSM216)")
    root.geometry("520x460")
    root.resizable(False, False)

    # Styling
    style = ttk.Style(root)
    style.theme_use("clam")

    # Variables
    mode_var = tk.StringVar(value="walk")
    speed_var = tk.IntVar(value=10)
    scenario_var = tk.StringVar(value="Standard Campus Route")
    explain_var = tk.BooleanVar(value=False)
    heatmap_var = tk.BooleanVar(value=False)

    # Main Container
    frame = ttk.Frame(root, padding="20 20 20 20")
    frame.grid(row=0, column=0, sticky="nsew")

    # Title Banner
    title_lbl = ttk.Label(
        frame,
        text="SafeRoute Simulator",
        font=("Segoe UI", 18, "bold"),
        foreground="#2c3e50",
    )
    title_lbl.grid(row=0, column=0, columnspan=2, pady=(0, 5), sticky="w")

    sub_lbl = ttk.Label(
        frame,
        text="B.Tech CSE Project (CSM216) | LPU / Chiheru Street Network",
        font=("Segoe UI", 10),
        foreground="#7f8c8d",
    )
    sub_lbl.grid(row=1, column=0, columnspan=2, pady=(0, 20), sticky="w")

    # 1. Travel Mode
    mode_lbl = ttk.Label(frame, text="Travel Mode:", font=("Segoe UI", 11, "bold"))
    mode_lbl.grid(row=2, column=0, sticky="w", pady=6)

    mode_frame = ttk.Frame(frame)
    mode_frame.grid(row=2, column=1, sticky="w", pady=6)
    ttk.Radiobutton(mode_frame, text="Walk (5 km/h)", variable=mode_var, value="walk").pack(side="left", padx=5)
    ttk.Radiobutton(mode_frame, text="Bike (15 km/h)", variable=mode_var, value="bike").pack(side="left", padx=5)
    ttk.Radiobutton(mode_frame, text="Car (OSM speed)", variable=mode_var, value="car").pack(side="left", padx=5)

    # 2. Simulation Speed Scale
    speed_lbl = ttk.Label(frame, text="Simulation Speed:", font=("Segoe UI", 11, "bold"))
    speed_lbl.grid(row=3, column=0, sticky="w", pady=6)

    speed_frame = ttk.Frame(frame)
    speed_frame.grid(row=3, column=1, sticky="w", pady=6)
    ttk.Radiobutton(speed_frame, text="1x (Real)", variable=speed_var, value=1).pack(side="left", padx=8)
    ttk.Radiobutton(speed_frame, text="10x (Demo)", variable=speed_var, value=10).pack(side="left", padx=8)
    ttk.Radiobutton(speed_frame, text="50x (Fast)", variable=speed_var, value=50).pack(side="left", padx=8)

    # 3. Scenario Selection
    scen_lbl = ttk.Label(frame, text="Initial Scenario:", font=("Segoe UI", 11, "bold"))
    scen_lbl.grid(row=4, column=0, sticky="w", pady=6)

    scen_combo = ttk.Combobox(
        frame,
        textvariable=scenario_var,
        values=[
            "Standard Campus Route",
            "Scripted Demo (Seed 42)",
            "Accident Obstacle Course",
        ],
        state="readonly",
        width=28,
    )
    scen_combo.grid(row=4, column=1, sticky="w", pady=6)

    # 4. Feature Checkbuttons
    opt_lbl = ttk.Label(frame, text="Options:", font=("Segoe UI", 11, "bold"))
    opt_lbl.grid(row=5, column=0, sticky="w", pady=6)

    opt_frame = ttk.Frame(frame)
    opt_frame.grid(row=5, column=1, sticky="w", pady=6)
    ttk.Checkbutton(opt_frame, text="Explain Mode (verbose trace)", variable=explain_var).pack(anchor="w")
    ttk.Checkbutton(opt_frame, text="Show Risk Heat-map", variable=heatmap_var).pack(anchor="w")

    # 5. Buttons
    btn_frame = ttk.Frame(frame)
    btn_frame.grid(row=6, column=0, columnspan=2, pady=(30, 10))

    def on_start():
        nonlocal settings
        settings = {
            "mode": mode_var.get(),
            "speed": speed_var.get(),
            "scenario": scenario_var.get(),
            "explain": explain_var.get(),
            "heatmap": heatmap_var.get(),
        }
        root.destroy()

    def on_cancel():
        root.destroy()

    start_btn = ttk.Button(btn_frame, text="Start Simulation (Enter)", command=on_start, width=22)
    start_btn.pack(side="left", padx=10)

    cancel_btn = ttk.Button(btn_frame, text="Exit", command=on_cancel, width=12)
    cancel_btn.pack(side="left", padx=10)

    # Keyboard shortcuts
    root.bind("<Return>", lambda e: on_start())
    root.bind("<Escape>", lambda e: on_cancel())

    root.mainloop()
    return settings
