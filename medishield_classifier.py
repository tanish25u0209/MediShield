"""
MediShield Visual Classifier
============================
Image classifier for medicine packaging form detection.

Target classes:
    Tablet | Capsule | Syrup | Injection | Other

Implementation:
    PyTorch + torchvision MobileNetV2 transfer learning

This version is designed to run on Python 3.14 in this workspace, where
TensorFlow wheels are not available.
"""

from __future__ import annotations

import json
import os
import random
import warnings
from collections import Counter
from pathlib import Path
from typing import Iterable

import matplotlib.pyplot as plt
import numpy as np
import seaborn as sns
import torch
from PIL import Image
from sklearn.metrics import classification_report, confusion_matrix
from sklearn.model_selection import train_test_split
from sklearn.utils.class_weight import compute_class_weight
from torch import nn
from torch.utils.data import DataLoader, Dataset
from torchvision import models, transforms
from torchvision.models import MobileNet_V2_Weights

warnings.filterwarnings("ignore")


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

CONFIG = {
    "data_roots": [
        str(
            Path.home()
            / ".cache"
            / "kagglehub"
            / "datasets"
            / "aryashah2k"
            / "mobile-captured-pharmaceutical-medication-packages"
            / "versions"
            / "1"
            / "Mobile-Captured Pharmaceutical Medication Packages"
        )
    ],
    "model_save_path": "medishield_classifier.pt",
    "metadata_path": "medishield_classifier.metadata.json",
    "classes": ["Tablet", "Capsule", "Syrup", "Injection", "Other"],
    "img_size": (224, 224),
    "batch_size": 32,
    "initial_epochs": 2,
    "finetune_epochs": 2,
    "learning_rate": 1e-3,
    "finetune_lr": 1e-4,
    "val_split": 0.2,
    "seed": 42,
}

NUM_CLASSES = len(CONFIG["classes"])
CLASS_TO_IDX = {name: idx for idx, name in enumerate(CONFIG["classes"])}
IDX_TO_CLASS = {idx: name for name, idx in CLASS_TO_IDX.items()}


# ---------------------------------------------------------------------------
# Reproducibility
# ---------------------------------------------------------------------------


def _seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


_seed_everything(CONFIG["seed"])


# ---------------------------------------------------------------------------
# Data discovery
# ---------------------------------------------------------------------------

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def _normalize_label_name(name: str) -> str:
    lower = name.lower()
    if any(
        token in lower
        for token in (
            "injection",
            "vial",
            "ampoule",
            "ampule",
            "injectable",
        )
    ):
        return "Injection"
    if any(
        token in lower
        for token in ("capsule", "capsules", "spansule", "softgel", "soft gels")
    ):
        return "Capsule"
    if any(
        token in lower
        for token in (
            "tablet",
            "tablets",
            "caplet",
            "caplets",
            "repetab",
            "repetabs",
            "chewable tablets",
        )
    ):
        return "Tablet"
    if any(
        token in lower
        for token in ("syrup", "elixir", "oral suspension", "suspension")
    ):
        return "Syrup"
    return "Other"


def infer_label_from_path(image_path: Path, root_dir: Path) -> str | None:
    """Infer the medicine form label from ancestor folder names."""
    current = image_path.parent
    while True:
        try:
            relative = current.relative_to(root_dir)
        except ValueError:
            break

        if str(relative) == ".":
            break

        folder_name = current.name.strip()
        if folder_name:
            label = _normalize_label_name(folder_name)
            if label != "Other":
                return label

        if current == root_dir:
            break
        current = current.parent

    return "Other"


def discover_samples(data_roots: Iterable[str]) -> list[tuple[str, int]]:
    """Collect image paths and assign them to the target classes."""
    samples: list[tuple[str, int]] = []
    for root in data_roots:
        root_path = Path(root)
        if not root_path.exists():
            continue

        for image_path in root_path.rglob("*"):
            if not image_path.is_file():
                continue
            if image_path.suffix.lower() not in IMAGE_EXTENSIONS:
                continue

            label_name = infer_label_from_path(image_path, root_path)
            if label_name not in CLASS_TO_IDX:
                continue
            samples.append((str(image_path), CLASS_TO_IDX[label_name]))

    return samples


# ---------------------------------------------------------------------------
# Dataset
# ---------------------------------------------------------------------------

IMAGENET_MEAN = (0.485, 0.456, 0.406)
IMAGENET_STD = (0.229, 0.224, 0.225)


class MedicineImageDataset(Dataset):
    def __init__(self, samples: list[tuple[str, int]], transform=None):
        self.samples = samples
        self.transform = transform

    def __len__(self) -> int:
        return len(self.samples)

    def __getitem__(self, index: int):
        image_path, label = self.samples[index]
        with Image.open(image_path) as image:
            image = image.convert("RGB")
            if self.transform is not None:
                image = self.transform(image)
        return image, label


def _build_transforms() -> tuple[transforms.Compose, transforms.Compose]:
    train_transform = transforms.Compose(
        [
            transforms.Resize((CONFIG["img_size"][0] + 16, CONFIG["img_size"][1] + 16)),
            transforms.RandomResizedCrop(CONFIG["img_size"], scale=(0.85, 1.0)),
            transforms.RandomHorizontalFlip(),
            transforms.RandomRotation(12),
            transforms.ColorJitter(brightness=0.2, contrast=0.15, saturation=0.1, hue=0.03),
            transforms.ToTensor(),
            transforms.Normalize(IMAGENET_MEAN, IMAGENET_STD),
        ]
    )

    val_transform = transforms.Compose(
        [
            transforms.Resize((CONFIG["img_size"][0], CONFIG["img_size"][1])),
            transforms.ToTensor(),
            transforms.Normalize(IMAGENET_MEAN, IMAGENET_STD),
        ]
    )

    return train_transform, val_transform


def load_data():
    """Build train and validation loaders from the discovered image dataset."""
    samples = discover_samples(CONFIG["data_roots"])
    if not samples:
        raise FileNotFoundError(
            "No training images were found. Check the KaggleHub download path in CONFIG['data_roots']."
        )

    labels = [label for _, label in samples]
    counts = Counter(labels)
    print("[load_data] Discovered samples:")
    for label_idx in sorted(counts):
        print(f"  [OK] {IDX_TO_CLASS[label_idx]:<9}: {counts[label_idx]}")

    train_samples, val_samples = train_test_split(
        samples,
        test_size=CONFIG["val_split"],
        random_state=CONFIG["seed"],
        stratify=labels,
    )

    train_transform, val_transform = _build_transforms()
    train_dataset = MedicineImageDataset(train_samples, transform=train_transform)
    val_dataset = MedicineImageDataset(val_samples, transform=val_transform)

    train_loader = DataLoader(
        train_dataset,
        batch_size=CONFIG["batch_size"],
        shuffle=True,
        num_workers=0,
        pin_memory=torch.cuda.is_available(),
    )
    val_loader = DataLoader(
        val_dataset,
        batch_size=CONFIG["batch_size"],
        shuffle=False,
        num_workers=0,
        pin_memory=torch.cuda.is_available(),
    )

    print(f"  [OK] Training samples  : {len(train_dataset)}")
    print(f"  [OK] Validation samples: {len(val_dataset)}")

    return train_loader, val_loader, samples


def preprocess_data(image_path: str) -> torch.Tensor:
    """Preprocess a single image for inference."""
    _, val_transform = _build_transforms()
    with Image.open(image_path) as image:
        image = image.convert("RGB")
        tensor = val_transform(image)
    return tensor.unsqueeze(0)


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


def build_model(freeze_base: bool = True) -> nn.Module:
    """Build a MobileNetV2 classifier with an updated classification head."""
    print(f"\n[build_model] Building model (freeze_base={freeze_base}) ...")
    weights = MobileNet_V2_Weights.DEFAULT
    model = models.mobilenet_v2(weights=weights)

    for parameter in model.features.parameters():
        parameter.requires_grad = not freeze_base

    in_features = model.classifier[1].in_features
    model.classifier = nn.Sequential(
        nn.Dropout(p=0.2),
        nn.Linear(in_features, NUM_CLASSES),
    )

    trainable_count = sum(parameter.numel() for parameter in model.parameters() if parameter.requires_grad)
    total_count = sum(parameter.numel() for parameter in model.parameters())
    print(f"  [OK] Trainable params  : {trainable_count:,}")
    print(f"  [OK] Total params      : {total_count:,}")
    return model


def _unfreeze_top_layers(model: nn.Module, n_blocks: int = 4) -> nn.Module:
    """Unfreeze the last MobileNetV2 feature blocks for fine-tuning."""
    for parameter in model.features.parameters():
        parameter.requires_grad = False

    feature_blocks = list(model.features.children())
    for block in feature_blocks[-n_blocks:]:
        for parameter in block.parameters():
            parameter.requires_grad = True

    for parameter in model.classifier.parameters():
        parameter.requires_grad = True

    unfrozen = sum(1 for parameter in model.parameters() if parameter.requires_grad)
    print(f"  [OK] Unfrozen parameter tensors: {unfrozen}")
    return model


# ---------------------------------------------------------------------------
# Training helpers
# ---------------------------------------------------------------------------


def _run_epoch(model: nn.Module, loader: DataLoader, criterion, optimizer, device: torch.device):
    model.train()
    total_loss = 0.0
    total_correct = 0
    total_samples = 0

    for images, labels in loader:
        images = images.to(device)
        labels = labels.to(device)

        optimizer.zero_grad(set_to_none=True)
        logits = model(images)
        loss = criterion(logits, labels)
        loss.backward()
        optimizer.step()

        batch_size = labels.size(0)
        total_loss += float(loss.item()) * batch_size
        total_correct += int((torch.argmax(logits, dim=1) == labels).sum().item())
        total_samples += batch_size

    return total_loss / max(total_samples, 1), total_correct / max(total_samples, 1)


@torch.no_grad()
def _evaluate_epoch(model: nn.Module, loader: DataLoader, criterion, device: torch.device):
    model.eval()
    total_loss = 0.0
    total_correct = 0
    total_samples = 0

    for images, labels in loader:
        images = images.to(device)
        labels = labels.to(device)
        logits = model(images)
        loss = criterion(logits, labels)

        batch_size = labels.size(0)
        total_loss += float(loss.item()) * batch_size
        total_correct += int((torch.argmax(logits, dim=1) == labels).sum().item())
        total_samples += batch_size

    return total_loss / max(total_samples, 1), total_correct / max(total_samples, 1)


def train_model(model: nn.Module, train_loader: DataLoader, val_loader: DataLoader):
    """Two-phase transfer learning training loop."""
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = model.to(device)

    class_weights = compute_class_weight(
        class_weight="balanced",
        classes=np.arange(NUM_CLASSES),
        y=[label for _, label in train_loader.dataset.samples],
    )
    weight_tensor = torch.tensor(class_weights, dtype=torch.float32, device=device)
    criterion = nn.CrossEntropyLoss(weight=weight_tensor)

    history: dict[str, list[float]] = {
        "loss": [],
        "val_loss": [],
        "accuracy": [],
        "val_accuracy": [],
    }

    best_state = None
    best_val_acc = -1.0
    patience = 4
    patience_left = patience

    print("\n[train_model] ── Phase 1: Feature Extraction (frozen base) ──")
    optimizer = torch.optim.Adam(
        (parameter for parameter in model.parameters() if parameter.requires_grad),
        lr=CONFIG["learning_rate"],
    )

    for epoch in range(CONFIG["initial_epochs"]):
        train_loss, train_acc = _run_epoch(model, train_loader, criterion, optimizer, device)
        val_loss, val_acc = _evaluate_epoch(model, val_loader, criterion, device)

        history["loss"].append(train_loss)
        history["accuracy"].append(train_acc)
        history["val_loss"].append(val_loss)
        history["val_accuracy"].append(val_acc)

        print(
            f"  Epoch {epoch + 1}/{CONFIG['initial_epochs']} - "
            f"loss={train_loss:.4f} acc={train_acc:.4f} val_loss={val_loss:.4f} val_acc={val_acc:.4f}"
        )

        if val_acc > best_val_acc:
            best_val_acc = val_acc
            best_state = model.state_dict()
            patience_left = patience
        else:
            patience_left -= 1
            if patience_left <= 0:
                print("  Early stopping triggered during phase 1.")
                break

    print("\n[train_model] ── Phase 2: Fine-Tuning (partial unfreeze) ──")
    model = _unfreeze_top_layers(model, n_blocks=4)
    optimizer = torch.optim.Adam(
        (parameter for parameter in model.parameters() if parameter.requires_grad),
        lr=CONFIG["finetune_lr"],
    )

    for epoch in range(CONFIG["finetune_epochs"]):
        train_loss, train_acc = _run_epoch(model, train_loader, criterion, optimizer, device)
        val_loss, val_acc = _evaluate_epoch(model, val_loader, criterion, device)

        history["loss"].append(train_loss)
        history["accuracy"].append(train_acc)
        history["val_loss"].append(val_loss)
        history["val_accuracy"].append(val_acc)

        print(
            f"  Epoch {epoch + 1}/{CONFIG['finetune_epochs']} - "
            f"loss={train_loss:.4f} acc={train_acc:.4f} val_loss={val_loss:.4f} val_acc={val_acc:.4f}"
        )

        if val_acc > best_val_acc:
            best_val_acc = val_acc
            best_state = model.state_dict()
            patience_left = patience
        else:
            patience_left -= 1
            if patience_left <= 0:
                print("  Early stopping triggered during phase 2.")
                break

    if best_state is not None:
        model.load_state_dict(best_state)

    _plot_training(history)
    return model, history


def _plot_training(history: dict[str, list[float]]):
    """Save accuracy and loss curves to disk."""
    fig, axes = plt.subplots(1, 2, figsize=(12, 4))

    axes[0].plot(history["accuracy"], label="Train Acc")
    axes[0].plot(history["val_accuracy"], label="Val Acc")
    axes[0].set_title("Accuracy")
    axes[0].legend()

    axes[1].plot(history["loss"], label="Train Loss")
    axes[1].plot(history["val_loss"], label="Val Loss")
    axes[1].set_title("Loss")
    axes[1].legend()

    plt.tight_layout()
    plt.savefig("training_curves.png", dpi=120)
    plt.close()
    print("  [OK] Training curves saved -> training_curves.png")


# ---------------------------------------------------------------------------
# Evaluation / Inference
# ---------------------------------------------------------------------------


@torch.no_grad()
def evaluate_model(model: nn.Module, val_loader: DataLoader):
    """Compute validation metrics and save a confusion matrix plot."""
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = model.to(device)
    model.eval()

    all_predictions: list[int] = []
    all_targets: list[int] = []

    for images, labels in val_loader:
        images = images.to(device)
        logits = model(images)
        predictions = torch.argmax(logits, dim=1).cpu().numpy().tolist()
        all_predictions.extend(predictions)
        all_targets.extend(labels.numpy().tolist())

    accuracy = float(np.mean(np.array(all_predictions) == np.array(all_targets)))
    print(f"\n[evaluate_model] Validation Accuracy: {accuracy:.4f}  ({accuracy * 100:.1f}%)")

    print("\n  ── Per-Class Report ──────────────────────────────────")
    print(
        classification_report(
            all_targets,
            all_predictions,
            target_names=CONFIG["classes"],
            zero_division=0,
        )
    )

    cm = confusion_matrix(all_targets, all_predictions)
    plt.figure(figsize=(7, 6))
    sns.heatmap(
        cm,
        annot=True,
        fmt="d",
        cmap="Blues",
        xticklabels=CONFIG["classes"],
        yticklabels=CONFIG["classes"],
    )
    plt.title("Confusion Matrix — MediShield Classifier")
    plt.xlabel("Predicted")
    plt.ylabel("Actual")
    plt.tight_layout()
    plt.savefig("confusion_matrix.png", dpi=120)
    plt.close()
    print("  [OK] Confusion matrix saved -> confusion_matrix.png")

    return {"accuracy": accuracy}


@torch.no_grad()
def predict_image(image_path: str, model: nn.Module) -> dict:
    """Run a single-image prediction."""
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = model.to(device)
    model.eval()

    arr = preprocess_data(image_path).to(device)
    logits = model(arr)[0]
    probabilities = torch.softmax(logits, dim=0)
    predicted_index = int(torch.argmax(probabilities).item())
    confidence = float(probabilities[predicted_index].item())

    return {
        "predicted_type": IDX_TO_CLASS[predicted_index],
        "confidence": round(confidence, 4),
        "all_scores": {
            class_name: round(float(probabilities[idx].item()), 4)
            for idx, class_name in IDX_TO_CLASS.items()
        },
        "anomaly_flag": confidence < 0.50,
        "anomaly_score": round(1.0 - confidence, 4),
    }


class BatchAnomalyTracker:
    """Track anomaly signals across a rolling window of predictions."""

    def __init__(self):
        self.predictions = []

    def add(self, result: dict):
        self.predictions.append(result)

    def compute_batch_anomaly(self) -> dict:
        if not self.predictions:
            return {"batch_anomaly_score": 0.0, "lot_inconsistency": False}

        scores = [prediction["anomaly_score"] for prediction in self.predictions]
        labels = [prediction["predicted_type"] for prediction in self.predictions]
        flags = [prediction["anomaly_flag"] for prediction in self.predictions]

        avg_anomaly_score = float(np.mean(scores))
        label_counts = Counter(labels)
        majority_count = label_counts.most_common(1)[0][1]
        lot_inconsistency = majority_count < len(labels) * 0.7

        flagged_ratio = sum(flags) / len(flags)
        combined_score = min(
            1.0,
            avg_anomaly_score + (0.3 * flagged_ratio) + (0.2 if lot_inconsistency else 0.0),
        )

        report = {
            "num_images": len(self.predictions),
            "avg_anomaly_score": round(avg_anomaly_score, 4),
            "flagged_ratio": round(flagged_ratio, 4),
            "lot_inconsistency": lot_inconsistency,
            "dominant_label": label_counts.most_common(1)[0][0],
            "combined_anomaly_score": round(combined_score, 4),
            "risk_level": (
                "HIGH" if combined_score > 0.6 else "MEDIUM" if combined_score > 0.3 else "LOW"
            ),
        }

        self.predictions.clear()
        return report


# ---------------------------------------------------------------------------
# Model export / load
# ---------------------------------------------------------------------------


def save_model(model: nn.Module):
    """Save the trained PyTorch model and metadata."""
    payload = {
        "model_state": model.state_dict(),
        "classes": CONFIG["classes"],
        "config": CONFIG,
    }
    torch.save(payload, CONFIG["model_save_path"])
    with open(CONFIG["metadata_path"], "w", encoding="utf-8") as handle:
        json.dump({"classes": CONFIG["classes"], "config": CONFIG}, handle, indent=2)
    print(f"\n  [OK] Model saved -> {CONFIG['model_save_path']}")


def load_trained_model() -> nn.Module:
    """Load a saved model for inference."""
    path = CONFIG["model_save_path"]
    if not os.path.exists(path):
        raise FileNotFoundError(f"Model not found at: {path}")

    payload = torch.load(path, map_location="cpu")
    model = build_model(freeze_base=False)
    model.load_state_dict(payload["model_state"])
    model.eval()
    print(f"  [OK] Model loaded from {path}")
    return model


# ---------------------------------------------------------------------------
# Main entrypoint
# ---------------------------------------------------------------------------


def main():
    """End-to-end training pipeline."""
    print("=" * 60)
    print("      MediShield — Visual Classification Module")
    print("=" * 60)

    train_loader, val_loader, samples = load_data()
    print(f"\n[main] Total usable images: {len(samples)}")

    model = build_model(freeze_base=True)

    model, history = train_model(model, train_loader, val_loader)
    metrics = evaluate_model(model, val_loader)
    save_model(model)

    print("\n[Demo] Simulated inference output:")
    demo_result = {
        "predicted_type": "Tablet",
        "confidence": 0.87,
        "all_scores": {
            "Tablet": 0.87,
            "Capsule": 0.06,
            "Syrup": 0.03,
            "Injection": 0.02,
            "Other": 0.02,
        },
        "anomaly_flag": False,
        "anomaly_score": 0.13,
    }
    print(json.dumps(demo_result, indent=2))

    print("\n[Done] Pipeline complete.")
    return model


if __name__ == "__main__":
    main()
