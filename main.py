"""
main.py – Entry point for SafeRoute Simulation (CSM216 Project).

Starts the Tkinter setup launcher window, then launches the Pygame simulation
with the user's selected parameters. Also supports CLI flags for rapid viva demos.
"""

import argparse
import sys


def main() -> None:
    """Launch the SafeRoute application."""
    parser = argparse.ArgumentParser(description="SafeRoute Desktop Simulator (CSM216)")
    parser.add_argument(
        "--no-launcher",
        action="store_true",
        help="Bypass Tkinter launcher and start Pygame simulation directly",
    )
    parser.add_argument(
        "--mode",
        choices=["walk", "bike", "car"],
        default="walk",
        help="Travel mode (walk, bike, car)",
    )
    parser.add_argument(
        "--speed",
        type=int,
        choices=[1, 10, 50],
        default=10,
        help="Simulation time acceleration scale (1, 10, 50)",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Launch directly into Scripted Demo (Seed 42)",
    )
    parser.add_argument(
        "--explain",
        action="store_true",
        help="Start with Dijkstra explain mode enabled",
    )
    parser.add_argument(
        "--heatmap",
        action="store_true",
        help="Start with risk heat-map overlay enabled",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run without graphical display (headless offscreen)",
    )
    parser.add_argument(
        "--max-frames",
        type=int,
        default=None,
        help="Maximum frames to run before auto-exiting",
    )

    args = parser.parse_args()

    # If flags passed that bypass launcher or run automated/demo mode
    if args.no_launcher or args.demo or args.headless or args.max_frames is not None:
        settings = {
            "mode": args.mode,
            "speed": args.speed,
            "explain": args.explain,
            "heatmap": args.heatmap,
            "scenario": "Scripted Demo (Seed 42)" if args.demo else "Standard Campus Route",
        }
    else:
        from ui.launcher import run_launcher
        settings = run_launcher()
        if settings is None:
            # User clicked Exit or closed the setup launcher
            sys.exit(0)

    from ui.pygame_app import run_simulation
    run_simulation(settings, max_frames=args.max_frames, headless=args.headless)


if __name__ == "__main__":
    main()
