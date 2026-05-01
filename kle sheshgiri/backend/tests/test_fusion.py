from modules.fusion import fuse_data, fuse_data_with_meta


def test_fuse_data_majority_vote() -> None:
    entries = [
        {"medicine_name": "Paracetamol", "batch_number": "B1", "exp_date": "01-01-2028"},
        {"medicine_name": "Paracetamol", "batch_number": "B1", "exp_date": "01-01-2028"},
        {"medicine_name": "Paracetamol", "batch_number": "B2", "exp_date": "01-01-2029"},
    ]

    fused = fuse_data(entries)
    assert fused["medicine_name"] == "Paracetamol"
    assert fused["batch_number"] == "B1"
    assert fused["exp_date"] == "2028-01-01"


def test_fuse_data_fills_missing_fields_from_other_images() -> None:
    entries = [
        {"medicine_name": "Dolo 650", "batch_number": "AB-12", "manufacturer": ""},
        {"medicine_name": "Dolo 650", "batch_number": "AB-12", "manufacturer": "Micro Labs"},
        {"medicine_name": "", "batch_number": "AB-12", "manufacturer": "N/A"},
    ]

    fused = fuse_data(entries)
    assert fused["medicine_name"] == "Dolo 650"
    assert fused["batch_number"] == "AB-12"
    assert fused["manufacturer"] == "Micro Labs"


def test_fuse_data_tie_break_is_deterministic() -> None:
    entries = [
        {"medicine_name": "Aspirin", "batch_number": "ZZ10"},
        {"medicine_name": "Crocin", "batch_number": "YY20"},
    ]
    quality = [
        {"blur_score": 400.0, "is_blurry": False, "is_low_quality": False, "is_distorted": False},
        {"blur_score": 100.0, "is_blurry": True, "is_low_quality": False, "is_distorted": False},
    ]

    fused_1, meta_1 = fuse_data_with_meta(entries, quality)
    fused_2, meta_2 = fuse_data_with_meta(entries, quality)

    assert fused_1 == fused_2
    assert fused_1["medicine_name"] == "Aspirin"
    assert meta_1 == meta_2
    assert meta_1["medicine_name"]["chosen_by"] == "fallback_quality"


def test_fusion_meta_contains_votes_and_conflict_flag() -> None:
    entries = [
        {"batch_number": "b1"},
        {"batch_number": "B1"},
        {"batch_number": "c2"},
    ]

    fused, meta = fuse_data_with_meta(entries)
    assert fused["batch_number"] == "B1"
    assert meta["batch_number"]["conflict"] is True
    assert meta["batch_number"]["votes"]["B1"] == 2
    assert "B1" in meta["batch_number"]["candidates"]


def test_majority_is_marked_as_majority_choice() -> None:
    entries = [
        {"manufacturer": "Micro Labs"},
        {"manufacturer": "micro labs"},
        {"manufacturer": "Another Pharma"},
    ]

    fused, meta = fuse_data_with_meta(entries)
    assert fused["manufacturer"] == "Micro Labs"
    assert meta["manufacturer"]["chosen_by"] == "majority"
