"""
Build an evaluation manifest from a folder of sample directories.

Expected folder layout:

root/
  sample_001/
    front.jpg
    back.jpg
    strip.jpg
    ground_truth.json   # optional
  sample_002/
    ...

Each sample folder should contain 1+ images. If `ground_truth.json` exists,
its values are copied into the manifest.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def _is_image(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS


def _load_ground_truth(sample_dir: Path) -> dict[str, Any]:
    truth_path = sample_dir / "ground_truth.json"
    if not truth_path.exists():
        return {}
    try:
        return json.loads(truth_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"Invalid JSON in {truth_path}: {exc}") from exc


def build_manifest(root: Path) -> dict[str, Any]:
    if not root.exists():
        raise FileNotFoundError(f"Sample root not found: {root}")

    samples: list[dict[str, Any]] = []

    for sample_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        images = sorted(str(path) for path in sample_dir.iterdir() if _is_image(path))
        if not images:
            continue

        sample = {
            "images": images,
            "ground_truth": _load_ground_truth(sample_dir),
        }

        if sample_dir.name:
            sample["sample_id"] = sample_dir.name

        samples.append(sample)

    return {"samples": samples}


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a MediShield eval manifest from sample folders.")
    parser.add_argument("--root", required=True, help="Root folder containing sample subfolders")
    parser.add_argument("--output", default="eval_manifest.json", help="Output manifest path")
    args = parser.parse_args()

    manifest = build_manifest(Path(args.root))
    Path(args.output).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Wrote {args.output} with {len(manifest['samples'])} samples")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
