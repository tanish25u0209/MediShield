"""
MediShield Evaluation Harness
=============================

Evaluates OCR, fusion, classifier, validation, and end-to-end performance
using a labeled manifest.

Expected manifest formats:
    1. JSON array of samples
    2. JSONL file, one JSON object per line

Recommended sample shape:
{
    "images": ["path/to/img1.jpg", "path/to/img2.jpg"],
    "ground_truth": {
        "medicine_name": "Amoxicillin",
        "batch_number": "BT2024A",
        "expiry_date": "06/2026",
        "mfg_date": "06/2024",
        "manufacturer": "Cipla Ltd"
    },
    "class_label": "Tablet",
    "expected_validation_flag": false,
    "expected_risk_level": "Safe"
}

Usage:
    python medishield_evaluation.py --manifest eval_manifest.json
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from difflib import SequenceMatcher
from typing import Any

import matplotlib.pyplot as plt
from sklearn.metrics import confusion_matrix, f1_score

from medishield_classifier import IDX_TO_CLASS, load_trained_model, predict_image
from medishield_ocr import process_medicine_images
from risk_engine import run_risk_engine


CORE_FIELDS = ["batch_number", "expiry_date", "mfg_date", "medicine_name"]
FIELD_WEIGHTS = {
    "batch_number": 0.4,
    "expiry_date": 0.3,
    "mfg_date": 0.2,
    "medicine_name": 0.1,
}


@dataclass
class MetricBucket:
    total: int = 0
    correct: int = 0
    exact_scores: list[float] = field(default_factory=list)
    fuzzy_scores: list[float] = field(default_factory=list)

    def add(self, exact: bool, fuzzy: float) -> None:
        self.total += 1
        self.correct += int(exact)
        self.exact_scores.append(1.0 if exact else 0.0)
        self.fuzzy_scores.append(fuzzy)

    def accuracy(self) -> float:
        return self.correct / self.total if self.total else 0.0

    def fuzzy_accuracy(self, threshold: float = 0.8) -> float:
        if not self.fuzzy_scores:
            return 0.0
        return sum(score >= threshold for score in self.fuzzy_scores) / len(self.fuzzy_scores)

    def average_fuzzy(self) -> float:
        if not self.fuzzy_scores:
            return 0.0
        return sum(self.fuzzy_scores) / len(self.fuzzy_scores)


def levenshtein_distance(a: str, b: str) -> int:
    a = a or ""
    b = b or ""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)

    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        curr = [i]
        for j, cb in enumerate(b, start=1):
            insert_cost = curr[j - 1] + 1
            delete_cost = prev[j] + 1
            replace_cost = prev[j - 1] + (ca != cb)
            curr.append(min(insert_cost, delete_cost, replace_cost))
        prev = curr
    return prev[-1]


def similarity_score(a: str, b: str) -> float:
    a = (a or "").strip()
    b = (b or "").strip()
    if not a and not b:
        return 1.0
    longest = max(len(a), len(b), 1)
    dist = levenshtein_distance(a.lower(), b.lower())
    lev_score = 1.0 - (dist / longest)
    seq_score = SequenceMatcher(None, a.lower(), b.lower()).ratio()
    return round(max(lev_score, seq_score), 4)


def weighted_field_score(field_scores: dict[str, float]) -> float:
    score = 0.0
    for field_name, weight in FIELD_WEIGHTS.items():
        score += weight * field_scores.get(field_name, 0.0)
    return round(score, 4)


def _bucket_label(confidence: float, step: float = 0.1) -> str:
    confidence = max(0.0, min(1.0, float(confidence)))
    start = int(confidence * 10) * 10
    end = min(100, start + 10)
    return f"{start:02d}-{end:02d}"


def _field_error_type(field_name: str, similarity: float, exact: bool) -> str | None:
    if exact:
        return None
    if similarity >= 0.8:
        return f"{field_name} near-match error"
    if similarity >= 0.5:
        return f"{field_name} parsing error"
    return f"{field_name} OCR error"


def _build_confidence_curve(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not points:
        return []

    buckets: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "correct": 0})
    for point in points:
        bucket = point["bucket"]
        buckets[bucket]["total"] += 1
        buckets[bucket]["correct"] += int(point["correct"])

    curve = []
    for bucket in sorted(buckets):
        total = buckets[bucket]["total"]
        correct = buckets[bucket]["correct"]
        low, high = bucket.split("-")
        mid = (int(low) + int(high)) / 2.0 / 100.0
        curve.append(
            {
                "bucket": bucket,
                "center_confidence": round(mid, 4),
                "accuracy": round(correct / total, 4) if total else 0.0,
                "count": total,
            }
        )
    return curve


def _save_confidence_curve_plot(curve: list[dict[str, Any]], output_path: str = "confidence_vs_accuracy.png") -> None:
    if not curve:
        return

    x = [point["center_confidence"] for point in curve]
    y = [point["accuracy"] for point in curve]
    counts = [point["count"] for point in curve]

    plt.figure(figsize=(8, 5))
    plt.plot(x, y, marker="o")
    for idx, count in enumerate(counts):
        plt.annotate(str(count), (x[idx], y[idx]), textcoords="offset points", xytext=(0, 8), ha="center")
    plt.ylim(0, 1.05)
    plt.xlabel("Confidence")
    plt.ylabel("Accuracy")
    plt.title("Confidence vs Accuracy")
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(output_path, dpi=140)
    plt.close()


def _top_hard_cases(failure_samples: list[dict[str, Any]], limit: int = 10) -> list[dict[str, Any]]:
    def severity(sample: dict[str, Any]) -> tuple[int, float, float]:
        error_type = sample.get("error_type", "")
        error_rank = {
            "ocr error": 3,
            "parsing error": 2,
            "fusion error": 2,
            "classifier error": 1,
        }.get(error_type, 1)
        fused_score = float(sample.get("fused_score", 0.0))
        single_score = float(sample.get("single_score", 0.0))
        return (error_rank, 1.0 - fused_score, 1.0 - single_score)

    return sorted(failure_samples, key=severity, reverse=True)[:limit]


def _build_error_distribution(primary_error_counts: Counter[str]) -> dict[str, float]:
    total = sum(primary_error_counts.values())
    if not total:
        return {}
    return {
        key: round((value / total) * 100.0, 2)
        for key, value in primary_error_counts.items()
    }


def _build_ocr_field_summary(
    single_counts: Counter[str],
    fused_counts: Counter[str],
    similarities: defaultdict[str, list[float]],
) -> dict[str, Any]:
    summary = {}
    field_rates = {}
    for field_name in CORE_FIELDS:
        single_total = single_counts.get(field_name, 0)
        fused_total = fused_counts.get(field_name, 0)
        avg_similarity = similarities[field_name]
        fused_rate = round((fused_total / max(len(avg_similarity), 1)) * 100.0, 2)
        field_rates[field_name] = fused_rate
        summary[field_name] = {
            "single_errors": single_total,
            "fused_errors": fused_total,
            "fused_error_rate": fused_rate,
            "average_similarity": round(sum(avg_similarity) / len(avg_similarity), 4) if avg_similarity else 0.0,
        }
    summary["most_failed_field"] = max(field_rates, key=field_rates.get) if field_rates else ""
    summary["field_error_rank"] = dict(sorted(field_rates.items(), key=lambda item: item[1], reverse=True))
    return summary


def load_manifest(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"Manifest not found: {path}")

    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return []

    if text.startswith("["):
        data = json.loads(text)
        if not isinstance(data, list):
            raise ValueError("JSON manifest must contain a top-level list.")
        return data

    samples: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if line:
            samples.append(json.loads(line))
    return samples


def _normalize_text(value: str) -> str:
    return " ".join((value or "").strip().split())


def evaluate_ocr_sample(sample: dict[str, Any]) -> dict[str, Any]:
    images = sample.get("images") or []
    if not images:
        raise ValueError("Sample must contain at least one image path.")

    ground_truth = sample.get("ground_truth") or {}
    single_result = process_medicine_images([images[0]])
    fused_result = process_medicine_images(images)

    return {
        "single": single_result,
        "fused": fused_result,
        "ground_truth": ground_truth,
    }


def _field_similarity_report(pred: dict[str, Any], gt: dict[str, Any]) -> tuple[dict[str, float], dict[str, bool]]:
    similarities: dict[str, float] = {}
    exact_matches: dict[str, bool] = {}
    for field_name in CORE_FIELDS:
        pred_value = _normalize_text(str(pred.get(field_name, "")))
        gt_value = _normalize_text(str(gt.get(field_name, "")))
        similarities[field_name] = similarity_score(pred_value, gt_value)
        exact_matches[field_name] = pred_value.lower() == gt_value.lower()
    return similarities, exact_matches


def _validation_expected(sample: dict[str, Any], fused_validation: dict[str, Any]) -> bool | None:
    expected = sample.get("expected_validation_flag")
    if expected is not None:
        return bool(expected)
    if fused_validation:
        return bool(fused_validation.get("issue_count", 0) > 0)
    return None


def _risk_expected(sample: dict[str, Any]) -> str | None:
    value = sample.get("expected_risk_level")
    return str(value) if value else None


def _score_risk_level(value: str) -> str:
    lower = (value or "").strip().lower()
    if lower in {"safe", "low"}:
        return "Safe"
    if lower in {"suspicious", "medium"}:
        return "Suspicious"
    if lower in {"high risk", "high", "danger"}:
        return "High Risk"
    return value or "Unknown"


def evaluate_manifest(manifest: list[dict[str, Any]], classifier_model_path: str | None = None) -> dict[str, Any]:
    if classifier_model_path is None:
        classifier_model = load_trained_model()
    else:
        classifier_model = load_trained_model()

    ocr_exact = MetricBucket()
    ocr_fuzzy = MetricBucket()
    single_ocr = MetricBucket()
    fused_ocr = MetricBucket()
    validation_hits = 0
    validation_total = 0

    classifier_total = 0
    classifier_correct = 0
    classifier_confidence_bins = defaultdict(lambda: {"total": 0, "correct": 0, "conf_sum": 0.0})
    classifier_errors: Counter[str] = Counter()
    system_total = 0
    system_correct = 0
    error_breakdown: Counter[str] = Counter()

    classifier_predictions: list[int] = []
    classifier_targets: list[int] = []
    confidence_curve_points: list[dict[str, Any]] = []
    failure_samples: list[dict[str, Any]] = []
    field_error_counts_single: Counter[str] = Counter()
    field_error_counts_fused: Counter[str] = Counter()
    field_similarity_totals: defaultdict[str, list[float]] = defaultdict(list)
    primary_error_counts: Counter[str] = Counter()

    for sample in manifest:
        images = sample.get("images") or []
        if not images:
            continue

        gt = sample.get("ground_truth") or {}
        class_label = sample.get("class_label")
        class_idx = None
        if class_label in IDX_TO_CLASS.values():
            class_idx = next(idx for idx, name in IDX_TO_CLASS.items() if name == class_label)

        ocr_outputs = evaluate_ocr_sample(sample)
        single_fields = ocr_outputs["single"]["final_data"]
        fused_fields = ocr_outputs["fused"]["final_data"]
        fused_validation = ocr_outputs["fused"].get("validation", {})

        similarities_single, exact_single = _field_similarity_report(single_fields, gt)
        similarities_fused, exact_fused = _field_similarity_report(fused_fields, gt)

        single_score = weighted_field_score(similarities_single)
        fused_score = weighted_field_score(similarities_fused)
        single_record_exact = all(exact_single.values())
        fused_record_exact = all(exact_fused.values())
        classifier_conf_bucket = _bucket_label(predicted_conf)

        single_ocr.add(single_record_exact, single_score)
        fused_ocr.add(fused_record_exact, fused_score)

        ocr_exact.add(fused_record_exact, 1.0 if fused_record_exact else 0.0)
        ocr_fuzzy.add(fused_score >= 0.8, fused_score)

        for field_name in CORE_FIELDS:
            field_similarity_totals[field_name].append(similarities_fused[field_name])
            if not exact_single[field_name]:
                field_error_counts_single[field_name] += 1
            if not exact_fused[field_name]:
                field_error_counts_fused[field_name] += 1

        expected_validation = _validation_expected(sample, fused_validation)
        if expected_validation is not None:
            validation_total += 1
            predicted_invalid = bool(fused_validation.get("issue_count", 0) > 0)
            validation_hits += int(predicted_invalid == expected_validation)

        classifier_result = predict_image(images[0], classifier_model)
        predicted_class = classifier_result["predicted_type"]
        predicted_conf = float(classifier_result["confidence"])

        if class_idx is not None:
            classifier_total += 1
            predicted_idx = next(idx for idx, name in IDX_TO_CLASS.items() if name == predicted_class)
            is_correct = predicted_idx == class_idx
            classifier_correct += int(is_correct)
            classifier_predictions.append(predicted_idx)
            classifier_targets.append(class_idx)

            bin_key = "low" if predicted_conf < 0.5 else "medium" if predicted_conf < 0.75 else "high"
            bucket = classifier_confidence_bins[bin_key]
            bucket["total"] += 1
            bucket["correct"] += int(is_correct)
            bucket["conf_sum"] += predicted_conf

            if not is_correct:
                error_breakdown["classifier error"] += 1

        decision = run_risk_engine(
            ocr_output=ocr_outputs["fused"],
            classifier_output={
                "predicted_class": predicted_class,
                "confidence": predicted_conf,
            },
            include_debug=False,
        )
        expected_risk = _risk_expected(sample)
        if expected_risk:
            system_total += 1
            predicted_risk = _score_risk_level(decision["status"])
            if predicted_risk.lower() == expected_risk.lower():
                system_correct += 1

        if class_idx is not None:
            confidence_curve_points.append(
                {
                    "confidence": round(predicted_conf, 4),
                    "correct": bool(predicted_class == IDX_TO_CLASS[class_idx]),
                    "bucket": classifier_conf_bucket,
                }
            )

        sample_error_types: list[str] = []
        if not fused_record_exact and single_record_exact:
            sample_error_types.append("fusion error")
        elif not fused_record_exact and not single_record_exact:
            sample_error_types.append("parsing error")
        elif not single_record_exact:
            sample_error_types.append("ocr error")

        if class_idx is not None and predicted_class != IDX_TO_CLASS[class_idx]:
            sample_error_types.append("classifier error")

        if sample_error_types:
            primary_error = sample_error_types[0]
            primary_error_counts[primary_error] += 1
            error_breakdown[primary_error] += 1
            failure_samples.append(
                {
                    "image_path": images[0],
                    "image_paths": images,
                    "ocr_output": {
                        "single": single_fields,
                        "fused": fused_fields,
                    },
                    "ground_truth": gt,
                    "error_type": primary_error,
                    "secondary_errors": sample_error_types[1:],
                    "single_score": round(single_score, 4),
                    "fused_score": round(fused_score, 4),
                    "classifier_confidence": round(predicted_conf, 4),
                    "classifier_prediction": predicted_class,
                }
            )

    classifier_bins_report = {}
    for name, bucket in classifier_confidence_bins.items():
        classifier_bins_report[name] = {
            "total": bucket["total"],
            "accuracy": round(bucket["correct"] / bucket["total"], 4) if bucket["total"] else 0.0,
            "avg_confidence": round(bucket["conf_sum"] / bucket["total"], 4) if bucket["total"] else 0.0,
        }

    macro_f1 = 0.0
    cm = []
    weak_classes: list[dict[str, Any]] = []
    confused_pair = None
    if classifier_targets:
        macro_f1 = f1_score(classifier_targets, classifier_predictions, average="macro", zero_division=0)
        label_order = sorted(IDX_TO_CLASS)
        cm = confusion_matrix(classifier_targets, classifier_predictions, labels=label_order).tolist()
        class_names = [IDX_TO_CLASS[idx] for idx in sorted(IDX_TO_CLASS)]
        recalls = []
        for idx, name in enumerate(class_names):
            row = cm[idx]
            row_total = sum(row)
            recall = (row[idx] / row_total) if row_total else 0.0
            recalls.append((recall, name))

        weak_classes = [
            {"class": name, "recall": round(recall, 4)}
            for recall, name in sorted(recalls, key=lambda item: item[0])[:2]
        ]

        worst_off_diag = 0
        for i, row in enumerate(cm):
            for j, value in enumerate(row):
                if i != j and value > worst_off_diag:
                    worst_off_diag = value
                    confused_pair = {
                        "actual": class_names[i],
                        "predicted": class_names[j],
                        "count": value,
                    }

    confidence_curve = _build_confidence_curve(confidence_curve_points)
    hard_cases = _top_hard_cases(failure_samples, limit=10)
    ocr_field_summary = _build_ocr_field_summary(
        field_error_counts_single,
        field_error_counts_fused,
        field_similarity_totals,
    )
    error_distribution = _build_error_distribution(primary_error_counts)
    _save_confidence_curve_plot(confidence_curve)

    report = {
        "ocr": {
            "exact_accuracy": round(ocr_exact.accuracy(), 4),
            "fuzzy_accuracy": round(ocr_fuzzy.fuzzy_accuracy(), 4),
            "avg_fuzzy_similarity": round(ocr_fuzzy.average_fuzzy(), 4),
            "weighted_score": round(fused_ocr.average_fuzzy(), 4),
            "field_weights": FIELD_WEIGHTS,
        },
        "fusion": {
            "single_image_score": round(single_ocr.average_fuzzy(), 4),
            "multi_image_score": round(fused_ocr.average_fuzzy(), 4),
            "improvement": round(fused_ocr.average_fuzzy() - single_ocr.average_fuzzy(), 4),
        },
        "classifier": {
            "accuracy": round(classifier_correct / classifier_total, 4) if classifier_total else 0.0,
            "macro_f1": round(macro_f1, 4),
            "confusion_matrix": cm,
            "weak_classes": weak_classes,
            "most_confused_pair": confused_pair,
            "confidence_calibration": classifier_bins_report,
        },
        "validation": {
            "correct_flags": round(validation_hits / validation_total, 4) if validation_total else 0.0,
            "evaluated_samples": validation_total,
        },
        "system": {
            "decision_accuracy": round(system_correct / system_total, 4) if system_total else 0.0,
            "reliable_cases": round(system_correct / system_total, 4) if system_total else 0.0,
            "evaluated_cases": system_total,
        },
        "error_breakdown": dict(error_breakdown),
        "error_distribution": error_distribution,
        "hard_cases": hard_cases,
        "confidence_curve": confidence_curve,
        "ocr_field_summary": ocr_field_summary,
    }

    return report


def print_report(report: dict[str, Any]) -> None:
    print("\nOCR Accuracy:")
    print(f"- Exact: {report['ocr']['exact_accuracy'] * 100:.1f}%")
    print(f"- Fuzzy: {report['ocr']['fuzzy_accuracy'] * 100:.1f}%")
    print(f"- Weighted Score: {report['ocr']['weighted_score'] * 100:.1f}%")

    print("\nFusion Improvement:")
    print(f"- Single image: {report['fusion']['single_image_score'] * 100:.1f}%")
    print(f"- Multi-image: {report['fusion']['multi_image_score'] * 100:.1f}%")
    print(f"- Improvement: {report['fusion']['improvement'] * 100:.1f}%")

    print("\nClassifier:")
    print(f"- Accuracy: {report['classifier']['accuracy'] * 100:.1f}%")
    for bucket_name, bucket in report["classifier"]["confidence_calibration"].items():
        print(
            f"- {bucket_name.title()} confidence: "
            f"acc={bucket['accuracy'] * 100:.1f}% avg_conf={bucket['avg_confidence'] * 100:.1f}%"
        )

    print("\nValidation Accuracy:")
    print(f"- Correct flags: {report['validation']['correct_flags'] * 100:.1f}%")

    print("\nOverall System:")
    print(f"- Reliable cases: {report['system']['reliable_cases'] * 100:.1f}%")

    print("\nError Distribution:")
    if report["error_distribution"]:
        for key, value in report["error_distribution"].items():
            print(f"- {key}: {value:.2f}%")
    else:
        print("- No failed samples recorded")

    print("\nOCR Field Summary:")
    for field_name, info in report["ocr_field_summary"].items():
        if field_name in {"most_failed_field", "field_error_rank"}:
            continue
        print(
            f"- {field_name}: single_errors={info['single_errors']} "
            f"fused_errors={info['fused_errors']} "
            f"avg_similarity={info['average_similarity']:.4f}"
        )
    if report["ocr_field_summary"].get("most_failed_field"):
        print(f"- Most failed field: {report['ocr_field_summary']['most_failed_field']}")

    print("\nHard Cases:")
    hard_cases = report.get("hard_cases", [])
    if hard_cases:
        for case in hard_cases[:10]:
            print(
                f"- {case['error_type']}: {case['image_path']} "
                f"(fused={case['fused_score']:.4f}, single={case['single_score']:.4f})"
            )
    else:
        print("- No hard cases recorded")

    if report.get("confidence_curve"):
        print("\nConfidence vs Accuracy:")
        for point in report["confidence_curve"]:
            print(
                f"- {point['bucket']}: acc={point['accuracy'] * 100:.1f}% "
                f"count={point['count']}"
            )

    print("\nError Breakdown:")
    if report["error_breakdown"]:
        for key, value in report["error_breakdown"].items():
            print(f"- {key}: {value}")
    else:
        print("- No errors recorded")


def main() -> int:
    parser = argparse.ArgumentParser(description="MediShield evaluation harness")
    parser.add_argument("--manifest", required=True, help="Path to JSON or JSONL evaluation manifest")
    parser.add_argument("--output", default="", help="Optional path to save the evaluation report as JSON")
    args = parser.parse_args()

    manifest = load_manifest(Path(args.manifest))
    report = evaluate_manifest(manifest)
    print_report(report)

    if args.output:
        Path(args.output).write_text(json.dumps(report, indent=2), encoding="utf-8")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
