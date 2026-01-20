"""
Service for generating fitpic static JPEG image collages.
7 images composited onto 1080x1350 canvas (4:5 aspect ratio).
No text overlays, no animations.
"""
import asyncio
import os
import subprocess
import logging
from typing import List, Dict

from models.schemas import FitpicRequest
from services.download_service import DownloadService

logger = logging.getLogger(__name__)


class FitpicService:
    """
    Handles fitpic static image collage creation via FFmpeg.
    Outputs a single JPEG image (no video, no text, no animations).
    """

    CANVAS_WIDTH = 1080
    CANVAS_HEIGHT = 1350  # 4:5 aspect ratio

    # Slot definitions based on fitpic.jpg layout (1080x1350 canvas)
    SLOT_LAYOUT = {
        "npc_logo":   {"pos": (20, 20),   "size": (425, 160)},   # Rectangle (logo, left)
        "brand_logo": {"pos": (635, 40),  "size": (425, 160)},   # Rectangle (logo, right)
        "hoodie":     {"pos": (40, 220),  "size": (550, 550)},   # Square (large, left) - moved right+down
        "pants":      {"pos": (40, 780),  "size": (550, 550)},   # Square (bottom left) - moved right
        "hat":        {"pos": (610, 240), "size": (383, 383)},   # Square (top right) - 10% smaller
        "meme":       {"pos": (625, 600), "size": (333, 333)},   # Square (middle right) - 10% smaller
        "shoes":      {"pos": (625, 980), "size": (333, 333)},   # Square (bottom right) - 10% smaller
    }

    # Overlay order controls z-index (later items are on top)
    OVERLAY_ORDER = ["npc_logo", "brand_logo", "hoodie", "pants", "hat", "meme", "shoes"]

    # Input order for API (matches order used in download tasks)
    INPUT_ORDER = ["npc_logo", "brand_logo", "hoodie", "hat", "meme", "shoes", "pants"]

    def __init__(self):
        self.download_service = DownloadService()

    async def create_fitpic_image(
        self,
        request: FitpicRequest,
        output_path: str
    ) -> Dict:
        """
        Build fitpic static image collage and return metadata.

        Args:
            request: FitpicRequest with image URLs for all slots
            output_path: Path for output JPEG file

        Returns:
            Dict with success status and metadata
        """
        image_paths: List[str] = []

        try:
            # Download all images concurrently
            download_tasks = [
                self.download_service.download_from_url(str(request.images[slot]))
                for slot in self.INPUT_ORDER
            ]
            results = await asyncio.gather(*download_tasks)
            image_paths = [path for path, _ in results]

            # Validate extensions
            for path in image_paths:
                ext = os.path.splitext(path)[1].lower()
                if ext not in {".jpg", ".jpeg", ".png"}:
                    raise ValueError("Only image inputs are allowed for fitpic template")

            total_input_size = sum(os.path.getsize(p) for p in image_paths)

            # Build filter complex for image compositing
            filter_complex = self._build_filter()

            # Build and execute FFmpeg command
            cmd = self._build_ffmpeg_command(
                filter_complex=filter_complex,
                image_paths=image_paths,
                output_path=output_path,
                quality=request.quality or 95
            )

            logger.info("Running fitpic FFmpeg command")
            logger.debug("FFmpeg command: %s", " ".join(cmd))

            process = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60  # Shorter timeout for static image
            )

            if process.returncode != 0:
                logger.error("Fitpic FFmpeg error: %s", process.stderr)
                raise RuntimeError(f"Fitpic processing failed: {process.stderr}")

            if not os.path.exists(output_path):
                raise RuntimeError("Fitpic output file not created")

            output_size = os.path.getsize(output_path)

            return {
                "success": True,
                "output_path": output_path,
                "output_size": output_size,
                "total_input_size": total_input_size
            }

        finally:
            for path in image_paths:
                self.download_service.cleanup_file(path)

    def _build_ffmpeg_command(
        self,
        filter_complex: str,
        image_paths: List[str],
        output_path: str,
        quality: int
    ) -> List[str]:
        """
        Construct the ffmpeg command for static JPEG output.

        Key differences from video services:
        - No duration, no loop on inputs
        - Uses -frames:v 1 for single frame
        - Uses -q:v for JPEG quality (1-31 scale, lower is better)
        """
        cmd: List[str] = [
            "ffmpeg",
            "-y",
            # Base canvas (white background)
            "-f", "lavfi",
            "-i", f"color=c=white:s={self.CANVAS_WIDTH}x{self.CANVAS_HEIGHT}",
        ]

        # Add each input image
        for path in image_paths:
            cmd.extend(["-i", path])

        # Convert quality from 1-100 scale to FFmpeg's 1-31 scale (inverted)
        # quality 100 -> q:v 1 (best), quality 1 -> q:v 31 (worst)
        ffmpeg_quality = max(1, min(31, 32 - int(quality * 0.31)))

        cmd.extend([
            "-filter_complex", filter_complex,
            "-map", "[final]",
            "-frames:v", "1",  # Single frame output
            "-q:v", str(ffmpeg_quality),
            output_path
        ])

        return cmd

    def _build_filter(self) -> str:
        """
        Build filter_complex string for image compositing.

        No text overlays, no fade effects - just image scaling and positioning.
        """
        filters: List[str] = []

        # Base canvas is input 0
        filters.append("[0:v]format=rgba[base]")

        # Prepare scaled inputs with names aligned to INPUT_ORDER
        for idx, slot_name in enumerate(self.INPUT_ORDER, start=1):
            size = self.SLOT_LAYOUT[slot_name]["size"]
            width, height = size
            filters.append(
                f"[{idx}:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
                f"crop={width}:{height},setsar=1[img_{slot_name}]"
            )

        # Overlay images in the defined z-order
        prev = "base"
        for i, slot_name in enumerate(self.OVERLAY_ORDER):
            pos = self.SLOT_LAYOUT[slot_name]["pos"]
            # Use unique label, final one will be [final]
            if i == len(self.OVERLAY_ORDER) - 1:
                next_label = "final"
            else:
                next_label = f"ov{i}"
            filters.append(
                f"[{prev}][img_{slot_name}]overlay={pos[0]}:{pos[1]}[{next_label}]"
            )
            prev = next_label

        return ";".join(filters)
