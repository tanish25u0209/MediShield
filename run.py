"""
Convenience launcher for the MediShield end-to-end pipeline.

Usage:
    python run.py img1.jpg img2.jpg
"""

from __future__ import annotations

from medishield_pipeline import main


if __name__ == "__main__":
    raise SystemExit(main())
