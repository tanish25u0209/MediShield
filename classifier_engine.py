"""
Classifier Engine - Packaging form classification wrapper.

Wraps existing MobileNetV2-based classifier in structured output format.
Handles per-image and consensus classification.
"""

import time
from typing import List, Optional
from pathlib import Path

from pipeline_schemas import (
    ClassifierPerImageResult,
    ClassifierEngineOutput,
    PackagingForm,
)


class ClassifierEngine:
    """Packaging form classification."""

    def __init__(self, model_path: Optional[str] = None):
        """Initialize classifier with optional model path."""
        self.model_path = model_path
        self.model = None
        self.class_names = None

        if model_path and Path(model_path).exists():
            self._load_model(model_path)

    def _load_model(self, model_path: str):
        """Load MobileNetV2 model. Deferred to actual implementation."""
        try:
            # Import here to avoid requiring torch if not using classifier
            import torch
            from torchvision import models

            self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

            # Load pretrained MobileNetV2
            self.model = models.mobilenet_v2(pretrained=True)
            self.model.to(self.device)
            self.model.eval()

            # Class names for packaging forms
            self.class_names = [
                PackagingForm.TABLET,
                PackagingForm.CAPSULE,
                PackagingForm.SYRUP,
                PackagingForm.INJECTION,
                PackagingForm.CREAM,
                PackagingForm.POWDER,
            ]

        except Exception as e:
            print(f"Warning: Failed to load classifier model: {e}")
            self.model = None
            self.class_names = None

    def classify_images(self, image_paths: List[str]) -> ClassifierEngineOutput:
        """Classify packaging form from multiple images."""
        start_time = time.time()
        per_image_results = []

        for image_path in image_paths:
            result = self._classify_single_image(image_path)
            per_image_results.append(result)

        # Determine consensus
        final_form, confidence = self._determine_consensus(per_image_results)

        processing_time = time.time() - start_time

        return ClassifierEngineOutput(
            final_form=final_form,
            confidence=confidence,
            per_image_results=per_image_results,
            consensus_method="majority_vote",
            processing_time_seconds=processing_time,
        )

    def _classify_single_image(self, image_path: str) -> ClassifierPerImageResult:
        """Classify a single image."""
        try:
            if self.model is None:
                # No model loaded - return unknown with zero confidence
                return ClassifierPerImageResult(
                    image_path=str(image_path),
                    predicted_form=PackagingForm.UNKNOWN,
                    confidence=0.0,
                )

            # Load and preprocess image
            import cv2
            import torch
            from torchvision import transforms

            img = cv2.imread(str(image_path))
            if img is None:
                return ClassifierPerImageResult(
                    image_path=str(image_path),
                    predicted_form=PackagingForm.UNKNOWN,
                    confidence=0.0,
                )

            # Resize to 224x224 for MobileNetV2
            img_resized = cv2.resize(img, (224, 224))
            img_rgb = cv2.cvtColor(img_resized, cv2.COLOR_BGR2RGB)

            # Normalize
            transform = transforms.Compose(
                [
                    transforms.ToTensor(),
                    transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
                ]
            )
            img_tensor = transform(img_rgb).unsqueeze(0).to(self.device)

            # Infer
            with torch.no_grad():
                outputs = self.model(img_tensor)
                probabilities = torch.nn.functional.softmax(outputs, dim=1)
                confidence, predicted_idx = torch.max(probabilities, 1)

            # Map to packaging form
            predicted_idx = predicted_idx.item()
            confidence = confidence.item()

            if predicted_idx < len(self.class_names):
                form = self.class_names[predicted_idx]
            else:
                form = PackagingForm.UNKNOWN

            return ClassifierPerImageResult(
                image_path=str(image_path),
                predicted_form=form,
                confidence=confidence,
            )

        except Exception as e:
            # Fallback on any error
            return ClassifierPerImageResult(
                image_path=str(image_path),
                predicted_form=PackagingForm.UNKNOWN,
                confidence=0.0,
            )

    def _determine_consensus(self, per_image_results: List[ClassifierPerImageResult]) -> tuple:
        """Determine consensus from per-image results."""
        if not per_image_results:
            return PackagingForm.UNKNOWN, 0.0

        if len(per_image_results) == 1:
            result = per_image_results[0]
            return result.predicted_form, result.confidence

        # Majority vote with confidence weighting
        vote_tally = {}
        for result in per_image_results:
            if result.predicted_form not in vote_tally:
                vote_tally[result.predicted_form] = 0.0
            vote_tally[result.predicted_form] += result.confidence

        # Determine winner
        winning_form = max(vote_tally.keys(), key=lambda k: vote_tally[k])
        winning_score = vote_tally[winning_form]

        # Normalize confidence
        total_confidence = sum(vote_tally.values())
        normalized_confidence = (winning_score / total_confidence) if total_confidence > 0 else 0.0

        return winning_form, normalized_confidence
