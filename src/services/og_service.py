"""
Service for repurposing user-provided videos with algorithmic uniqueness.

Applies the same transformations as Stein:
- Random fade-in duration (0.2s - 1.25s)
- Random fade-in black opacity (69% - 88%)
- Random subtle stretch (0.3-12% horizontal OR vertical)
- Random slowdown (0-20%)
- Logo at 22% opacity, position changes every 2 seconds
"""
import os
import random
import subprocess
import logging
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)


class OGService:
    """Repurposes user-provided videos with algorithmic uniqueness."""

    # Logo URL (same as Stein)
    LOGO_URL = "https://storage.nocodecult.io/stein/logo/insidelabel_white.png"

    # Output dimensions (9:16 aspect ratio)
    CANVAS_WIDTH = 1080
    CANVAS_HEIGHT = 1920

    # Randomization parameters (same as Stein)
    MIN_FADE_IN = 0.20
    MAX_FADE_IN = 1.25
    MIN_FADE_BLACK_OPACITY = 0.69  # 31% video visible at start
    MAX_FADE_BLACK_OPACITY = 0.88  # 12% video visible at start
    MIN_STRETCH_PERCENT = 0.3  # 0.3% stretch
    MAX_STRETCH_PERCENT = 12.0  # 12% stretch
    MIN_SLOWDOWN_PERCENT = 0
    MAX_SLOWDOWN_PERCENT = 20  # Up to 20% slower
    LOGO_OPACITY = 0.22
    LOGO_SIZE = 333  # Width in pixels (height auto-scaled)
    POSITION_CHANGE_INTERVAL = 2  # seconds

    # Safe margins for logo placement
    LOGO_MARGIN = 75  # Minimum distance from edges

    def __init__(self):
        self._download_service = None

    def _get_download_service(self):
        """Lazy load download service."""
        if self._download_service is None:
            from services.download_service import DownloadService
            self._download_service = DownloadService()
        return self._download_service

    async def _download_video(self, video_url: str) -> str:
        """Download video from URL and return local path."""
        download_service = self._get_download_service()
        local_path, _ = await download_service.download_from_url(video_url)
        return local_path

    async def _get_logo(self) -> str:
        """Download logo from R2 and return local path."""
        download_service = self._get_download_service()
        local_path, _ = await download_service.download_from_url(self.LOGO_URL)
        return local_path

    def _get_video_duration(self, video_path: str) -> float:
        """Get the duration of a video using ffprobe."""
        cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            video_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            raise RuntimeError(f"Failed to get video duration: {result.stderr}")
        return float(result.stdout.strip())

    def _generate_random_positions(self, count: int) -> List[Tuple[int, int]]:
        """Generate random (x, y) positions for logo within safe bounds."""
        positions = []
        max_x = self.CANVAS_WIDTH - self.LOGO_SIZE - self.LOGO_MARGIN
        max_y = self.CANVAS_HEIGHT - self.LOGO_SIZE - self.LOGO_MARGIN

        for _ in range(count):
            x = random.randint(self.LOGO_MARGIN, max_x)
            y = random.randint(self.LOGO_MARGIN, max_y)
            positions.append((x, y))

        return positions

    def _build_position_expression(
        self,
        positions: List[Tuple[int, int]],
        coord_index: int  # 0 for x, 1 for y
    ) -> str:
        """
        Build FFmpeg expression for position that changes every 2 seconds.

        For 3 positions at t=0, t=2, t=4:
        if(lt(t,2),P1,if(lt(t,4),P2,P3))
        """
        if len(positions) == 1:
            return str(positions[0][coord_index])

        coords = [str(pos[coord_index]) for pos in positions]

        # Build nested if expression
        # Start from the last position and work backwards
        expr = coords[-1]
        for i in range(len(coords) - 2, -1, -1):
            threshold = (i + 1) * self.POSITION_CHANGE_INTERVAL
            expr = f"if(lt(t\\,{threshold})\\,{coords[i]}\\,{expr})"

        return expr

    def _build_filter_complex(
        self,
        fade_duration: float,
        fade_black_opacity: float,
        stretch_direction: str,
        stretch_amount: int,
        slowdown_percent: float,
        positions: List[Tuple[int, int]]
    ) -> str:
        """Build the FFmpeg filter_complex string."""
        filters = []

        # Step 1: Scale with stretch, then crop back to exact dimensions
        if stretch_direction == "horizontal":
            scale_w = self.CANVAS_WIDTH + stretch_amount
            scale_h = self.CANVAS_HEIGHT
        else:  # vertical
            scale_w = self.CANVAS_WIDTH
            scale_h = self.CANVAS_HEIGHT + stretch_amount

        # Calculate PTS multiplier for slowdown (e.g., 7% slower = 1.0753x PTS)
        pts_multiplier = 1.0 / (1.0 - slowdown_percent / 100.0)

        filters.append(
            f"[0:v]scale={scale_w}:{scale_h}:force_original_aspect_ratio=disable,"
            f"crop={self.CANVAS_WIDTH}:{self.CANVAS_HEIGHT},setsar=1,"
            f"setpts={pts_multiplier:.4f}*PTS[scaled]"
        )

        # Step 2: Apply fade-in from partial black (not pure black)
        # Create black overlay that starts at fade_black_opacity and fades to transparent
        filters.append(
            f"color=black:size={self.CANVAS_WIDTH}x{self.CANVAS_HEIGHT},"
            f"format=rgba,colorchannelmixer=aa={fade_black_opacity},"
            f"fade=t=out:st=0:d={fade_duration}:alpha=1[black]"
        )
        filters.append(
            f"[scaled][black]overlay=shortest=1[faded]"
        )

        # Step 3: Prepare logo with opacity
        filters.append(
            f"[1:v]format=rgba,scale={self.LOGO_SIZE}:-1,"
            f"colorchannelmixer=aa={self.LOGO_OPACITY}[logo]"
        )

        # Step 4: Overlay logo with position changing every 2 seconds
        x_expr = self._build_position_expression(positions, 0)
        y_expr = self._build_position_expression(positions, 1)

        filters.append(
            f"[faded][logo]overlay=x='{x_expr}':y='{y_expr}':"
            f"enable='gte(t,{fade_duration})':eof_action=repeat[out]"
        )

        return ";".join(filters)

    async def create_og_video(self, video_url: str, output_path: str) -> Dict:
        """
        Create an algorithmically unique video from a user-provided video URL.

        Returns metadata about the processing.
        """
        video_path = None
        logo_path = None
        temp_files = []

        try:
            # Download video from URL
            video_path = await self._download_video(video_url)
            if video_path.startswith("/tmp") or "/temp/" in video_path:
                temp_files.append(video_path)
            logger.info(f"Downloaded video: {video_url}")

            # Get logo
            logo_path = await self._get_logo()
            if logo_path.startswith("/tmp") or "/temp/" in logo_path:
                temp_files.append(logo_path)

            # Get video duration for position calculation
            duration = self._get_video_duration(video_path)
            num_positions = max(1, int(duration / self.POSITION_CHANGE_INTERVAL) + 1)

            # Randomize all parameters
            fade_duration = random.uniform(self.MIN_FADE_IN, self.MAX_FADE_IN)
            fade_black_opacity = random.uniform(self.MIN_FADE_BLACK_OPACITY, self.MAX_FADE_BLACK_OPACITY)
            stretch_direction = random.choice(["horizontal", "vertical"])
            stretch_percent = random.uniform(self.MIN_STRETCH_PERCENT, self.MAX_STRETCH_PERCENT)
            # Calculate pixels based on direction (horizontal=1080, vertical=1920)
            base_dimension = self.CANVAS_WIDTH if stretch_direction == "horizontal" else self.CANVAS_HEIGHT
            stretch_amount = int(base_dimension * stretch_percent / 100)
            slowdown_percent = random.uniform(self.MIN_SLOWDOWN_PERCENT, self.MAX_SLOWDOWN_PERCENT)
            positions = self._generate_random_positions(num_positions)

            logger.info(
                f"Randomized params: fade={fade_duration:.2f}s@{fade_black_opacity:.0%}black, "
                f"stretch={stretch_direction}+{stretch_percent:.1f}%({stretch_amount}px), "
                f"slowdown={slowdown_percent:.1f}%, "
                f"positions={positions}"
            )

            # Build filter complex
            filter_complex = self._build_filter_complex(
                fade_duration=fade_duration,
                fade_black_opacity=fade_black_opacity,
                stretch_direction=stretch_direction,
                stretch_amount=stretch_amount,
                slowdown_percent=slowdown_percent,
                positions=positions
            )

            # Build FFmpeg command
            creation_time = datetime.now(ZoneInfo("America/New_York")).isoformat(timespec="seconds")

            cmd = [
                "ffmpeg", "-y",
                "-i", video_path,
                "-i", logo_path,
                "-filter_complex", filter_complex,
                "-map", "[out]",
                "-c:v", "libx264",
                "-preset", "slow",
                "-crf", "18",
                "-pix_fmt", "yuv420p",
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
            ]

            logger.info("Running OG FFmpeg command")
            logger.debug("FFmpeg command: %s", " ".join(cmd))

            process = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300  # 5 minutes timeout for longer videos
            )

            if process.returncode != 0:
                logger.error(f"OG FFmpeg error: {process.stderr}")
                raise RuntimeError(f"OG processing failed: {process.stderr}")

            if not os.path.exists(output_path):
                raise RuntimeError("OG output file not created")

            output_size = os.path.getsize(output_path)

            return {
                "success": True,
                "output_path": output_path,
                "output_size": output_size,
                "fade_duration": fade_duration,
                "fade_black_opacity": fade_black_opacity,
                "stretch_direction": stretch_direction,
                "stretch_amount": stretch_amount,
                "slowdown_percent": slowdown_percent,
                "num_logo_positions": num_positions
            }

        finally:
            # Cleanup downloaded temp files
            for temp_file in temp_files:
                try:
                    if os.path.exists(temp_file):
                        os.remove(temp_file)
                        logger.debug(f"Cleaned up temp file: {temp_file}")
                except Exception as e:
                    logger.warning(f"Failed to cleanup temp file {temp_file}: {e}")
