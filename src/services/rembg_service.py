"""
Background Removal Service using rembg with GPU acceleration.
Uses birefnet-general model for best quality.
"""
import logging
from typing import Optional, List
from rembg import remove, new_session

logger = logging.getLogger(__name__)

# Pre-load the birefnet-general model at import time (stays in GPU memory)
# This eliminates cold start delay for subsequent requests
MODEL_NAME = "birefnet-general"
logger.info(f"Pre-loading rembg model: {MODEL_NAME}")
DEFAULT_SESSION = new_session(MODEL_NAME)
logger.info(f"Model {MODEL_NAME} loaded successfully")


class RembgService:
    """Wrapper around rembg with GPU-accelerated model session."""

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.sessions = {MODEL_NAME: DEFAULT_SESSION}  # Pre-loaded session

    def get_session(self, model: str):
        """Get or create a session for the specified model."""
        if model not in self.sessions:
            self.logger.info(f"Loading rembg model: {model}")
            self.sessions[model] = new_session(model)
        return self.sessions[model]

    def remove_background(
        self,
        input_path: str,
        output_path: str,
        model: str = "birefnet-general",  # Best quality model
        alpha_matting: bool = False,       # Disabled - causes holes in white items
        foreground_threshold: int = 240,
        background_threshold: int = 15,
        erode_size: int = 8,
        post_process_mask: bool = True,
        bgcolor: Optional[List[int]] = None
    ) -> None:
        """
        Remove background from image with GPU acceleration.

        Uses birefnet-general by default for best quality results.
        Alpha matting is disabled as it causes issues with white items.
        """
        session = self.get_session(model)

        with open(input_path, "rb") as f:
            data = f.read()

        # Build kwargs - only include alpha_matting params if enabled
        kwargs = {
            "session": session,
            "post_process_mask": post_process_mask,
        }

        if alpha_matting:
            kwargs.update({
                "alpha_matting": True,
                "alpha_matting_foreground_threshold": foreground_threshold,
                "alpha_matting_background_threshold": background_threshold,
                "alpha_matting_erode_size": erode_size,
            })

        if bgcolor:
            kwargs["bgcolor"] = tuple(bgcolor)

        result = remove(data, **kwargs)

        with open(output_path, "wb") as f:
            f.write(result)

        self.logger.info(f"Background removed (model={model}, alpha={alpha_matting}) -> {output_path}")
