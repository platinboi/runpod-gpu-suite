"""
Service for generating outfit-single (v2) collage videos.
5 overlapping square images with black header.
"""
import asyncio
import os
import tempfile
import logging
import random
import textwrap
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import List, Tuple, Dict, Optional

from config import Config
from models.schemas import (
    OutfitSingleRequest,
    MIN_OUTFIT_SINGLE_DURATION,
    MAX_OUTFIT_SINGLE_DURATION,
    MIN_OUTFIT_SINGLE_FADE_IN,
    MAX_OUTFIT_SINGLE_FADE_IN
)
from services.download_service import DownloadService

logger = logging.getLogger(__name__)


class OutfitSingleService:
    """
    Handles outfit-single (v2) collage creation via FFmpeg.
    5 overlapping square images with black header.
    """

    CANVAS_WIDTH = 1080
    CANVAS_HEIGHT = 1920
    HEADER_HEIGHT = 280  # Black band at top (taller for title + subtitle)

    # Text defaults
    TITLE_FONT_SIZE_DEFAULT = 64
    SUBTITLE_FONT_SIZE_DEFAULT = 38

    BORDER_WIDTH = 0  # Clean text on solid header
    SHADOW_X = 0
    SHADOW_Y = 0

    # Slot definitions (top-left origin). All squares.
    # Main images (hat, hoodie, pants, shoes) are centered horizontally
    # Extra is smaller and right-aligned
    SLOT_LAYOUT = {
        "hoodie": {"pos": (270, 590), "size": 540},   # centered: (1080-540)/2 = 270
        "hat":    {"pos": (365, 320), "size": 350},   # centered: (1080-350)/2 = 365
        "pants":  {"pos": (290, 1060), "size": 500},  # centered, +60px down
        "extra":  {"pos": (680, 825), "size": 280},   # right side meme
        "meme":   {"pos": (120, 980), "size": 250},   # left side meme (smaller)
        "shoes":  {"pos": (370, 1450), "size": 340},  # centered, +70px down
    }

    # Overlay order controls z-index (later items are on top)
    OVERLAY_ORDER = ["hoodie", "hat", "meme", "pants", "extra", "shoes"]

    # Input order for API (matches request schema field order)
    INPUT_ORDER = ["hat", "hoodie", "extra", "meme", "pants", "shoes"]

    def __init__(self):
        self.download_service = DownloadService()
        self._database_service = None

    def _get_database_service(self):
        """Lazy load database service."""
        if self._database_service is None:
            from services.database_service import DatabaseService
            self._database_service = DatabaseService()
        return self._database_service

    async def _get_random_sound(self) -> Optional[Tuple[str, str]]:
        """
        Get a random sound from the database and download it.
        Returns (local_path, sound_name) or None if no sounds available.
        """
        try:
            db = self._get_database_service()
            sound = db.get_random_sound()
            if not sound:
                logger.warning("No sounds available in tiktok_sounds table")
                return None

            local_path, _ = await self.download_service.download_from_url(sound['url'])
            return local_path, sound['name']
        except Exception as e:
            logger.error(f"Failed to get random sound: {e}")
            return None

    async def create_outfit_single_video(
        self,
        request: OutfitSingleRequest,
        output_path: str
    ) -> Dict:
        """
        Build outfit-single collage video and return metadata.
        """
        image_paths: List[str] = []
        text_files: List[str] = []
        sound_path: Optional[str] = None
        sound_name: Optional[str] = None
        temp_files: List[str] = []

        try:
            # Get random sound for audio track
            sound_result = await self._get_random_sound()
            if sound_result:
                sound_path, sound_name = sound_result
                temp_files.append(sound_path)
                logger.info(f"Selected sound: {sound_name}")

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
                    raise ValueError("Only image inputs are allowed for outfit-single template")

            total_input_size = sum(os.path.getsize(p) for p in image_paths)

            # Font sizes (overridable)
            title_font_size = request.title_font_size or self.TITLE_FONT_SIZE_DEFAULT
            subtitle_font_size = request.subtitle_font_size or self.SUBTITLE_FONT_SIZE_DEFAULT

            # Wrap text to avoid clipping
            wrapped_title, title_lines = self._wrap_text(
                request.main_title,
                font_size=title_font_size,
                max_width_px=self.CANVAS_WIDTH - 160  # ~80px margin each side
            )
            wrapped_subtitle, subtitle_lines = self._wrap_text(
                request.subtitle or "",
                font_size=subtitle_font_size,
                max_width_px=self.CANVAS_WIDTH - 160
            )

            # Vertical offsets for multi-line titles
            extra_title_lines = max(0, title_lines - 1)
            title_up = extra_title_lines * title_font_size * 0.55
            subtitle_down = extra_title_lines * title_font_size * 0.1

            title_y = 95 - title_up  # Centered within taller header band
            subtitle_y = 215 + subtitle_down

            # Prepare text files
            main_title_file = self._write_text_file(wrapped_title, text_files)
            subtitle_file = self._write_text_file(wrapped_subtitle, text_files)

            # Fade and duration
            fade_in_requested = (
                request.fade_in
                if request.fade_in is not None
                else random.uniform(MIN_OUTFIT_SINGLE_FADE_IN, MAX_OUTFIT_SINGLE_FADE_IN)
            )
            fade_in = max(MIN_OUTFIT_SINGLE_FADE_IN, min(fade_in_requested, MAX_OUTFIT_SINGLE_FADE_IN))

            duration_requested = request.duration
            duration_jitter = random.uniform(-0.75, 0.75)
            duration = max(
                MIN_OUTFIT_SINGLE_DURATION,
                min(MAX_OUTFIT_SINGLE_DURATION, duration_requested + duration_jitter)
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

            cmd = self._build_ffmpeg_command(
                filter_complex=filter_complex,
                image_paths=image_paths,
                duration=duration,
                output_path=output_path,
                creation_time=creation_time
            )

            logger.info("Running outfit-single FFmpeg command")
            logger.debug("FFmpeg command: %s", " ".join(cmd))

            import subprocess

            process = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=180
            )

            if process.returncode != 0:
                logger.error("Outfit-single FFmpeg error: %s", process.stderr)
                raise RuntimeError(f"Outfit-single processing failed: {process.stderr}")

            if not os.path.exists(output_path):
                raise RuntimeError("Outfit-single output file not created")

            # Add audio track if sound was downloaded
            if sound_path and os.path.exists(sound_path):
                from services.ffmpeg_service import FFmpegService

                # Create temp file for video without audio
                video_no_audio = output_path + ".noaudio.mp4"
                os.rename(output_path, video_no_audio)
                temp_files.append(video_no_audio)

                try:
                    FFmpegService.add_audio_track(
                        video_path=video_no_audio,
                        audio_path=sound_path,
                        output_path=output_path
                    )
                    logger.info(f"Added audio track: {sound_name}")
                except Exception as e:
                    logger.error(f"Failed to add audio track: {e}")
                    # Restore original video without audio
                    if os.path.exists(video_no_audio):
                        os.rename(video_no_audio, output_path)
                    sound_name = None  # Mark as failed

            output_size = os.path.getsize(output_path)

            return {
                "success": True,
                "output_path": output_path,
                "output_size": output_size,
                "total_input_size": total_input_size,
                "sound_name": sound_name
            }

        finally:
            for path in image_paths:
                self.download_service.cleanup_file(path)
            for path in text_files:
                try:
                    if os.path.exists(path):
                        os.remove(path)
                except Exception as e:
                    logger.warning("Failed to cleanup text temp file %s: %s", path, e)
            for path in temp_files:
                try:
                    if os.path.exists(path):
                        os.remove(path)
                except Exception as e:
                    logger.warning("Failed to cleanup temp file %s: %s", path, e)

    def _wrap_text(self, text: str, font_size: int, max_width_px: int) -> Tuple[str, int]:
        """Wrap text based on approximate character width; returns wrapped text and line count."""
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

        # Base video with black header band
        filters.append(
            f"[0:v]format=rgba,"
            f"drawbox=x=0:y=0:w=iw:h={self.HEADER_HEIGHT}:color=black@1:t=fill[base0]"
        )

        # Prepare scaled inputs with names aligned to INPUT_ORDER
        for idx, slot_name in enumerate(self.INPUT_ORDER, start=1):
            size = self.SLOT_LAYOUT[slot_name]["size"]
            filters.append(
                f"[{idx}:v]scale={size}:{size}:force_original_aspect_ratio=increase,"
                f"crop={size}:{size},setsar=1[img_{slot_name}]"
            )

        # Overlay images in the defined z-order
        prev = "base0"
        for i, slot_name in enumerate(self.OVERLAY_ORDER, start=1):
            pos = self.SLOT_LAYOUT[slot_name]["pos"]
            next_label = f"ov{i}"
            filters.append(
                f"[{prev}][img_{slot_name}]overlay={pos[0]}:{pos[1]}:shortest=1[{next_label}]"
            )
            prev = next_label

        # Fade the body (images + header) before text is applied
        slow_ramp_until = 0.9
        early_gamma = 0.75
        filters.append(f"[{prev}]fade=t=in:st=0:d={fade_in}[faded_body]")
        filters.append(
            f"[faded_body]eq=gamma={early_gamma}:enable='between(t,0,{slow_ramp_until})'[leveled_body]"
        )
        prev = "leveled_body"

        font_path = Config.TIKTOK_SANS_SEMIBOLD

        # Title (white on black header, no fade)
        filters.append(
            f"[{prev}]drawtext=fontfile='{font_path}':textfile='{main_title_file}':"
            f"fontsize={title_font_size}:fontcolor=white:bordercolor=black:borderw={self.BORDER_WIDTH}:"
            f"shadowcolor=black@0.0:shadowx={self.SHADOW_X}:shadowy={self.SHADOW_Y}:"
            f"x=(w-text_w)/2:y={title_y}[txt_main]"
        )
        prev = "txt_main"

        # Subtitle (white on black header, appears after 2.5s)
        filters.append(
            f"[{prev}]drawtext=fontfile='{font_path}':textfile='{subtitle_file}':"
            f"fontsize={subtitle_font_size}:fontcolor=white:bordercolor=black:borderw={self.BORDER_WIDTH}:"
            f"shadowcolor=black@0.0:shadowx={self.SHADOW_X}:shadowy={self.SHADOW_Y}:"
            f"x=(w-text_w)/2:y={subtitle_y}:enable='gte(t,2.5)'[txt_sub]"
        )
        prev = "txt_sub"

        # Final format
        filters.append(f"[{prev}]format=yuv420p[video_out]")

        return ";".join(filters)
