"""
Service for generating 9-image outfit collage videos.
"""
import asyncio
import os
import tempfile
import uuid
import logging
import random
import textwrap
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import List, Tuple, Dict

from config import Config
from models.schemas import (
    OutfitRequest,
    MIN_OUTFIT_FADE_IN,
    MAX_OUTFIT_FADE_IN,
    MIN_OUTFIT_DURATION,
    MAX_OUTFIT_DURATION
)
from services.download_service import DownloadService

logger = logging.getLogger(__name__)


class OutfitService:
    """Handles outfit collage creation via FFmpeg"""

    CANVAS_WIDTH = 1080
    CANVAS_HEIGHT = 1920
    TILE_SIZE = 380  # Larger images, more compact layout
    TILE_X = [40, 350, 660]  # Left/right moved inward
    TILE_Y = [435, 891, 1361]
    LABEL_OFFSET_Y = -70
    LABEL_FONT_SIZE = 80
    TITLE_FONT_SIZE_DEFAULT = 74
    SUBTITLE_FONT_SIZE_DEFAULT = 40
    BORDER_WIDTH = 6
    SHADOW_X = 3
    SHADOW_Y = 3

    def __init__(self):
        self.download_service = DownloadService()

    async def create_outfit_video(
        self,
        request: OutfitRequest,
        output_path: str
    ) -> Dict:
        """
        Build outfit collage video and return metadata.
        """
        image_paths: List[str] = []
        text_files: List[str] = []
        try:
            # Download all images concurrently
            download_tasks = [
                self.download_service.download_from_url(str(url))
                for url in request.image_urls
            ]
            results: List[Tuple[str, str]] = await asyncio.gather(*download_tasks)
            image_paths = [path for path, _ in results]

            # Validate image extensions (only images, square-ish later)
            for path in image_paths:
                ext = os.path.splitext(path)[1].lower()
                if ext not in {".jpg", ".jpeg", ".png"}:
                    raise ValueError("Only image inputs are allowed for outfit")

            total_input_size = sum(os.path.getsize(p) for p in image_paths)

            # Font sizes (overridable)
            requested_title_font_size = request.title_font_size or self.TITLE_FONT_SIZE_DEFAULT
            title_font_size = int(round(requested_title_font_size * 0.92))
            subtitle_font_size = request.subtitle_font_size or self.SUBTITLE_FONT_SIZE_DEFAULT

            # Wrap text to avoid clipping; returns wrapped string and line counts
            wrapped_title, title_lines = self._wrap_text(
                request.main_title,
                font_size=title_font_size,
                max_width_px=self.CANVAS_WIDTH - 160
            )
            wrapped_subtitle, subtitle_lines = self._wrap_text(
                request.subtitle or "",
                font_size=subtitle_font_size,
                max_width_px=self.CANVAS_WIDTH - 160
            )

            # Vertical offsets:
            # - Push title upward when it wraps
            # - Push subtitle slightly downward when title wraps to avoid overlap
            extra_title_lines = max(0, title_lines - 1)
            title_up = extra_title_lines * title_font_size * 0.65
            subtitle_down = extra_title_lines * title_font_size * 0.05

            title_y = 170 - title_up
            subtitle_y = 285 + subtitle_down

            # Prepare text files for main and subtitle to avoid escaping issues
            main_title_file = self._write_text_file(wrapped_title, text_files)
            subtitle_file = self._write_text_file(wrapped_subtitle, text_files)

            fade_in_requested = (
                request.fade_in
                if request.fade_in is not None
                else random.uniform(MIN_OUTFIT_FADE_IN, MAX_OUTFIT_FADE_IN)
            )
            fade_in = max(MIN_OUTFIT_FADE_IN, min(fade_in_requested, MAX_OUTFIT_FADE_IN))

            # Slightly randomize duration to ±0.75s while staying in bounds
            duration_requested = request.duration
            duration_jitter = random.uniform(-0.75, 0.75)
            duration = max(
                MIN_OUTFIT_DURATION,
                min(MAX_OUTFIT_DURATION, duration_requested + duration_jitter)
            )

            filter_complex = self._build_filter(
                main_title_file=main_title_file,
                subtitle_file=subtitle_file,
                fade_in=fade_in,
                title_font_size=title_font_size,
                subtitle_font_size=subtitle_font_size,
                title_y=title_y,
                subtitle_y=subtitle_y
            )

            creation_time = datetime.now(ZoneInfo("America/New_York")).isoformat(timespec="seconds")

            # Build FFmpeg command
            cmd = self._build_ffmpeg_command(
                filter_complex=filter_complex,
                image_paths=image_paths,
                duration=duration,
                output_path=output_path,
                creation_time=creation_time
            )

            logger.info("Running outfit FFmpeg command")
            logger.debug("FFmpeg command: %s", " ".join(cmd))

            import subprocess

            process = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=180
            )

            if process.returncode != 0:
                logger.error("Outfit FFmpeg error: %s", process.stderr)
                raise RuntimeError(f"Outfit processing failed: {process.stderr}")

            if not os.path.exists(output_path):
                raise RuntimeError("Outfit output file not created")

            output_size = os.path.getsize(output_path)

            return {
                "success": True,
                "output_path": output_path,
                "output_size": output_size,
                "total_input_size": total_input_size
            }

        finally:
            # Cleanup temp files
            for path in image_paths:
                self.download_service.cleanup_file(path)
            for path in text_files:
                try:
                    if os.path.exists(path):
                        os.remove(path)
                except Exception as e:
                    logger.warning("Failed to cleanup text temp file %s: %s", path, e)

    def _wrap_text(self, text: str, font_size: int, max_width_px: int) -> Tuple[str, int]:
        """
        Wrap text based on an approximate character width so long headings don't clip.
        Returns the wrapped text and number of lines.
        """
        if not text:
            return "", 0
        avg_char_px = max(font_size * 0.55, 1)
        max_chars = max(1, int(max_width_px / avg_char_px))
        lines = textwrap.wrap(text, width=max_chars)
        if not lines:
            return "", 0
        return "\n".join(lines), len(lines)

    def _write_text_file(self, content: str, registry: List[str]) -> str:
        """Create a temp text file and register for cleanup."""
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".txt", mode="w", encoding="utf-8")
        tmp.write(content)
        tmp.flush()
        tmp.close()
        registry.append(tmp.name)
        return tmp.name

    def _build_ffmpeg_command(
        self,
        filter_complex: str,
        image_paths: List[str],
        duration: float,
        output_path: str,
        creation_time: str
    ) -> List[str]:
        """Construct the ffmpeg command."""
        cmd: List[str] = [
            "ffmpeg",
            "-y",
            "-f", "lavfi",
            "-t", f"{duration}",
            "-i", f"color=c=white:s={self.CANVAS_WIDTH}x{self.CANVAS_HEIGHT}:r=30:d={duration}"
        ]

        for path in image_paths:
            cmd.extend([
                "-loop", "1",
                "-t", f"{duration}",
                "-i", path
            ])

        cmd.extend([
            "-filter_complex", filter_complex,
            "-map", "[video_out]",
            "-t", f"{duration}",
            "-c:v", "libx264",
            "-preset", "slow",
            "-crf", "18",
            "-pix_fmt", "yuv420p",
            # Clean and spoof lightweight Apple/iPhone metadata (New York, USA)
            "-map_metadata", "-1",
            "-map_chapters", "-1",
            "-metadata", "major_brand=mp42",
            "-metadata", "minor_version=0",
            "-metadata", "compatible_brands=mp42isom",
            "-metadata", "com.apple.quicktime.make=Apple",
            "-metadata", "com.apple.quicktime.model=iPhone 17 Pro",
            "-metadata", "com.apple.quicktime.software=iOS 17.2.1",
            "-metadata", f"creation_time={creation_time}",
            "-metadata", "com.apple.quicktime.location.ISO6709=+40.7128-074.0060+000.00/",
            "-metadata", "com.apple.quicktime.location.name=New York, NY, USA",
            "-metadata", "location=+40.7128-074.0060+000.00/",
            "-metadata:s:v:0", "handler_name=Core Media Video",
            "-movflags", "+faststart+use_metadata_tags",
            "-an",
            output_path
        ])
        return cmd

    def _build_filter(
        self,
        main_title_file: str,
        subtitle_file: str,
        fade_in: float,
        title_font_size: int,
        subtitle_font_size: int,
        title_y: float,
        subtitle_y: float
    ) -> str:
        """Build filter_complex string for layout, text, and fade."""
        filters: List[str] = []

        # Base video from color source
        filters.append("[0:v]format=rgba[base0]")

        # Prepare scaled inputs
        for idx in range(1, 10):
            filters.append(
                f"[{idx}:v]scale={self.TILE_SIZE}:{self.TILE_SIZE}:force_original_aspect_ratio=increase,"
                f"crop={self.TILE_SIZE}:{self.TILE_SIZE},setsar=1[img{idx}]"
            )

        # Overlay tiles
        prev = "base0"
        tile_positions = self._tile_positions()
        for i, (x, y) in enumerate(tile_positions, start=1):
            next_label = f"ov{i}"
            filters.append(f"[{prev}][img{i}]overlay={x}:{y}:shortest=1[{next_label}]")
            prev = next_label

        # Fade body (images + labels) before adding always-visible header text
        slow_ramp_until = 0.9
        early_gamma = 0.75  # gentle dimming during the first 0.9s to slow the lift
        filters.append(f"[{prev}]fade=t=in:st=0:d={fade_in}[faded_body]")
        filters.append(
            f"[faded_body]eq=gamma={early_gamma}:enable='between(t,0,{slow_ramp_until})'[leveled_body]"
        )
        prev = "leveled_body"

        # Titles (do NOT fade)
        font_path = Config.TIKTOK_SANS_SEMIBOLD
        filters.append(
            f"[{prev}]drawtext=fontfile='{font_path}':textfile='{main_title_file}':"
            f"fontsize={title_font_size}:fontcolor=white:bordercolor=black:borderw={self.BORDER_WIDTH}:"
            f"shadowcolor=black@0.6:shadowx={self.SHADOW_X}:shadowy={self.SHADOW_Y}:"
            f"x=(w-text_w)/2:y={title_y}[txt_main]"
        )
        prev = "txt_main"

        filters.append(
            f"[{prev}]drawtext=fontfile='{font_path}':textfile='{subtitle_file}':"
            f"fontsize={subtitle_font_size}:fontcolor=white:bordercolor=black:borderw={self.BORDER_WIDTH}:"
            f"shadowcolor=black@0.6:shadowx={self.SHADOW_X}:shadowy={self.SHADOW_Y}:"
            f"x=(w-text_w)/2:y={subtitle_y}:enable='gte(t,2.5)'[txt_sub]"
        )
        prev = "txt_sub"

        # Labels A-F,1-3 at tile centers with Y offset
        label_texts = ["A\\:", "B\\:", "C\\:", "1\\:", "2\\:", "3\\:", "D\\:", "E\\:", "F\\:"]
        label_positions = self._label_positions()
        for i, ((x, y), text) in enumerate(zip(label_positions, label_texts)):
            next_label = f"label{i}"
            filters.append(
                f"[{prev}]drawtext=fontfile='{font_path}':text='{text}':"
                f"fontsize={self.LABEL_FONT_SIZE}:fontcolor=white:bordercolor=black:borderw={self.BORDER_WIDTH}:"
                f"shadowcolor=black@0.6:shadowx={self.SHADOW_X}:shadowy={self.SHADOW_Y}:"
                f"x={x}-text_w/2:y={y}[{next_label}]"
            )
            prev = next_label

        # Fade in and pixel format
        # Final format conversion
        filters.append(f"[{prev}]format=yuv420p[video_out]")

        return ";".join(filters)

    def _tile_positions(self) -> List[Tuple[int, int]]:
        """Cartesian product of X and Y coordinates for 3x3 grid."""
        positions: List[Tuple[int, int]] = []
        for y in self.TILE_Y:
            for x in self.TILE_X:
                positions.append((x, y))
        return positions

    def _label_positions(self) -> List[Tuple[int, int]]:
        """Center positions for labels above each tile."""
        positions: List[Tuple[int, int]] = []
        for y in self.TILE_Y:
            label_y = y + self.LABEL_OFFSET_Y
            for x in self.TILE_X:
                center_x = x + self.TILE_SIZE // 2
                positions.append((center_x, label_y))
        return positions

