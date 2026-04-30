"""
Backward Compatibility Adapter - Bridges new modular pipeline to existing evaluation harness.

Allows existing evaluation scripts to use the new modular pipeline without modification.
Converts new structured outputs to legacy formats.
"""

from typing import List, Dict, Any, Optional
from pathlib import Path

from pipeline_orchestrator import PipelineOrchestrator
from pipeline_schemas import MediShieldPipelineOutput, convert_to_legacy_format


class MediShieldPipelineAdapter:
    """
    Adapter for backward compatibility with existing evaluation harness.
    
    Existing code like medishield_evaluation.py expects:
    - process_medicine_images(image_paths) -> dict
    
    New code provides:
    - MediShieldPipelineOutput structured dataclass
    
    This adapter bridges the gap transparently.
    """

    def __init__(self, classifier_model_path: Optional[str] = None):
        """Initialize adapter with orchestrator."""
        self.orchestrator = PipelineOrchestrator(classifier_model_path)

    def process_medicine_images(self, image_paths: List[str]) -> Dict[str, Any]:
        """
        Process images with new pipeline, return in legacy format.
        
        Args:
            image_paths: List of image file paths
            
        Returns:
            Dictionary matching original format for evaluation compatibility
        """
        # Process with new pipeline
        pipeline_output: MediShieldPipelineOutput = self.orchestrator.process_medicine_images(
            image_paths
        )

        # Return legacy-compatible output
        return pipeline_output.backward_compatibility_data

    def process_medicine_images_new(self, image_paths: List[str]) -> MediShieldPipelineOutput:
        """
        Process images with new pipeline, return structured output.
        
        This is the recommended interface for new code.
        
        Args:
            image_paths: List of image file paths
            
        Returns:
            MediShieldPipelineOutput with full structured data
        """
        return self.orchestrator.process_medicine_images(image_paths)

    def get_structured_output(self, legacy_output: Dict[str, Any]) -> Dict[str, Any]:
        """Convert legacy output back to structured format (for backwards exploration)."""
        # In practice, you'd already have the structured output from process_medicine_images_new
        # This is here for completeness if someone only has legacy output
        return {
            "warning": "This conversion is lossy. Use process_medicine_images_new() for full structured output."
        }


# ============================================================================
# Helper for existing scripts
# ============================================================================

def create_adapter(classifier_model_path: Optional[str] = None) -> MediShieldPipelineAdapter:
    """Factory function to create adapter."""
    return MediShieldPipelineAdapter(classifier_model_path)


# ============================================================================
# Compatibility exports for existing imports
# ============================================================================

# If existing code does: from medishield_pipeline import process_medicine
# These exports provide the legacy interface

_adapter = None


def get_adapter() -> MediShieldPipelineAdapter:
    """Lazy-load adapter singleton."""
    global _adapter
    if _adapter is None:
        _adapter = MediShieldPipelineAdapter()
    return _adapter


def process_medicine(image_paths: List[str]) -> Dict[str, Any]:
    """
    Legacy function signature for backward compatibility.
    
    Usage (existing code):
        from medishield_pipeline import process_medicine
        result = process_medicine(["img1.jpg", "img2.jpg"])
    """
    return get_adapter().process_medicine_images(image_paths)
