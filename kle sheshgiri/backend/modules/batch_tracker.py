"""Batch tracking module - tracks batch numbers when scanned and detects duplicates/patterns."""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from collections import defaultdict

# Store batch lookup history in memory (in production, use database)
_BATCH_HISTORY = defaultdict(list)
_BATCH_FILE = Path(__file__).parent.parent / "data" / "batch_history.json"


def _ensure_data_dir():
    """Ensure data directory exists."""
    _BATCH_FILE.parent.mkdir(parents=True, exist_ok=True)


def _load_batch_history():
    """Load batch history from file."""
    global _BATCH_HISTORY
    _ensure_data_dir()
    if _BATCH_FILE.exists():
        try:
            with open(_BATCH_FILE, 'r') as f:
                data = json.load(f)
                # Convert to defaultdict(list)
                _BATCH_HISTORY = defaultdict(list)
                for batch_num, records in data.items():
                    _BATCH_HISTORY[batch_num] = records
        except Exception:
            _BATCH_HISTORY = defaultdict(list)


def _save_batch_history():
    """Save batch history to file."""
    _ensure_data_dir()
    try:
        with open(_BATCH_FILE, 'w') as f:
            # Convert defaultdict to regular dict for JSON serialization
            json.dump(dict(_BATCH_HISTORY), f, indent=2)
    except Exception as e:
        print(f"Error saving batch history: {e}")


def record_batch_lookup(batch_number: str, medicine_name: str, location: str = "Unknown") -> dict:
    """
    Record a batch lookup.
    
    Args:
        batch_number: The batch number being scanned
        medicine_name: The medicine name
        location: Optional location of the scan
        
    Returns:
        Dict with batch info and whether it's a duplicate
    """
    if not batch_number or not batch_number.strip():
        return {"recorded": False, "batch": None}
    
    batch = batch_number.strip().upper()
    
    # Load current history
    _load_batch_history()
    
    # Create new record
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "medicine": medicine_name,
        "location": location,
    }
    
    # Check if this batch was seen before
    is_duplicate = len(_BATCH_HISTORY[batch]) > 0
    occurrences = len(_BATCH_HISTORY[batch]) + 1  # Including this one
    
    # Add record
    _BATCH_HISTORY[batch].append(record)
    _save_batch_history()
    
    return {
        "recorded": True,
        "batch": batch,
        "is_duplicate": is_duplicate,
        "occurrences": occurrences,
        "medicine": medicine_name,
        "first_seen": _BATCH_HISTORY[batch][0]["timestamp"] if len(_BATCH_HISTORY[batch]) > 0 else None,
    }


def get_batch_history(batch_number: str) -> dict:
    """
    Get the history of a batch number.
    
    Args:
        batch_number: The batch number to look up
        
    Returns:
        Dict with batch history data for visualization
    """
    if not batch_number or not batch_number.strip():
        return {"found": False, "batch": None, "records": []}
    
    batch = batch_number.strip().upper()
    
    # Load current history
    _load_batch_history()
    
    records = _BATCH_HISTORY.get(batch, [])
    
    if not records:
        return {
            "found": False,
            "batch": batch,
            "records": [],
            "total_occurrences": 0,
        }
    
    # Prepare graph data
    times = []
    medicines = []
    locations = []
    colors = []
    
    for i, rec in enumerate(records):
        times.append(rec["timestamp"].split('T')[1].split('.')[0] if 'T' in rec["timestamp"] else rec["timestamp"])
        medicines.append(rec.get("medicine", "Unknown"))
        locations.append(rec.get("location", "Unknown"))
        # Color by location or sequential
        colors.append(_get_color_for_location(rec.get("location", "Unknown")))
    
    return {
        "found": True,
        "batch": batch,
        "records": records,
        "total_occurrences": len(records),
        "graph_data": {
            "times": times,
            "medicines": medicines,
            "locations": locations,
            "colors": colors,
        },
    }


def _get_color_for_location(location: str) -> str:
    """Get a consistent color for a location."""
    colors = {
        "Mumbai": "#ff5f57",
        "Delhi": "#ffbc42",
        "Pune": "#58a6ff",
        "Hyderabad": "#4f9eff",
        "Unknown": "#8b93ab",
    }
    return colors.get(location, "#8b93ab")


def clear_batch_history(batch_number: Optional[str] = None):
    """Clear batch history (all or specific batch)."""
    global _BATCH_HISTORY
    _load_batch_history()
    if batch_number:
        batch = batch_number.strip().upper()
        if batch in _BATCH_HISTORY:
            del _BATCH_HISTORY[batch]
    else:
        _BATCH_HISTORY.clear()
    _save_batch_history()
