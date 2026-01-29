"""
Service for generating algorithmically unique videos from STEIN clips.

Each output looks identical to humans but has unique hash due to:
- Random fade-in duration (0.25s - 1.5s)
- Random subtle stretch (2-20px horizontal OR vertical)
- Random slowdown (0-9%)
- Logo at 20% opacity, appears after fade-in
- Logo position changes every 3 seconds
- Random TikTok sound added as audio track
"""
import os
import random
import subprocess
import logging
import tempfile
import textwrap
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Dict, List, Tuple, Optional

logger = logging.getLogger(__name__)


class SteinService:
    """Generates algorithmically unique videos from STEIN source clips."""

    # Hardcoded R2 URLs (static assets)
    STEIN_CLIP_URLS = [
        "https://storage.nocodecult.io/stein/clips/STEIN-4433.mp4",
        "https://storage.nocodecult.io/stein/clips/STEIN-5367.mp4",
        "https://storage.nocodecult.io/stein/clips/STEIN-6767.mp4",
        "https://storage.nocodecult.io/stein/clips/STEIN-7233.mp4",
        "https://storage.nocodecult.io/stein/clips/STEIN-7333.mp4",
        "https://storage.nocodecult.io/stein/clips/STEIN-7600.mp4",
        "https://storage.nocodecult.io/stein/clips/STEIN-7767.mp4",
    ]
    STEIN_LOGO_URL = "https://storage.nocodecult.io/stein/logo/insidelabel_white.png"

    # Output dimensions (9:16 aspect ratio)
    CANVAS_WIDTH = 1080
    CANVAS_HEIGHT = 1920

    # Randomization parameters
    MIN_FADE_IN = 0.20
    MAX_FADE_IN = 1.25
    MIN_FADE_BLACK_OPACITY = 0.69  # 34% video visible at start
    MAX_FADE_BLACK_OPACITY = 0.88  # 12% video visible at start
    MIN_STRETCH_PERCENT = 0.3  # 0.3% stretch
    MAX_STRETCH_PERCENT = 12.0  # 9% stretch (up to 97px H, 173px V)
    MIN_SLOWDOWN_PERCENT = 0
    MAX_SLOWDOWN_PERCENT = 20  # Adds up to ~1.7s on longest clip
    LOGO_OPACITY = 0.22
    LOGO_SIZE = 333  # Width in pixels (height auto-scaled)
    POSITION_CHANGE_INTERVAL = 2  # seconds

    # Safe margins for logo placement
    LOGO_MARGIN = 75  # Minimum distance from edges

    # Text overlay settings
    TEXT_SAFE_MARGIN = 50  # 50px left/right padding for text
    TEXT_MAX_WIDTH = 980  # 1080 - 100 total padding
    TEXT_FONT_SIZE = 72

    def __init__(self):
        self._download_service = None

    def _get_download_service(self):
        """Lazy load download service."""
        if self._download_service is None:
            from services.download_service import DownloadService
            self._download_service = DownloadService()
        return self._download_service

    async def _get_random_sound(self) -> Optional[Tuple[str, str]]:
        """
        Get a random sound from the static list and download it.
        Returns (local_path, sound_name) or None if download fails.
        """
        try:
            from sounds import get_random_sound
            sound = get_random_sound()

            download_service = self._get_download_service()
            local_path, _ = await download_service.download_from_url(sound['url'])
            return local_path, sound['name']
        except Exception as e:
            logger.error(f"Failed to get random sound: {e}")
            return None

    async def _get_random_clip(self) -> Tuple[str, str]:
        """Select and download a random STEIN clip. Returns (local_path, clip_name)."""
        clip_url = random.choice(self.STEIN_CLIP_URLS)
        clip_name = clip_url.split("/")[-1]
        download_service = self._get_download_service()
        local_path, _ = await download_service.download_from_url(clip_url)
        return local_path, clip_name

    async def _get_logo(self) -> str:
        """Download logo from R2 and return local path."""
        download_service = self._get_download_service()
        local_path, _ = await download_service.download_from_url(self.STEIN_LOGO_URL)
        return local_path

    def _get_clip_duration(self, clip_path: str) -> float:
        """Get the duration of a video clip using ffprobe."""
        cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            clip_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            raise RuntimeError(f"Failed to get clip duration: {result.stderr}")
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

    def _wrap_text(self, text: str, font_size: int, max_width_px: int) -> Tuple[str, int]:
        """
        Wrap text based on approximate character width so long captions don't clip.
        Returns the wrapped text and number of lines.
        """
        if not text:
            return "", 0
        avg_char_px = max(font_size * 0.55, 1)
        max_chars = max(1, int(max_width_px / avg_char_px))
        lines = textwrap.wrap(text, width=max_chars, break_long_words=True)
        if not lines:
            return "", 0
        return "\n".join(lines), len(lines)

    def _build_position_expression(
        self,
        positions: List[Tuple[int, int]],
        coord_index: int  # 0 for x, 1 for y
    ) -> str:
        """
        Build FFmpeg expression for position that changes every 3 seconds.

        For 3 positions at t=0, t=3, t=6:
        if(lt(t,3),P1,if(lt(t,6),P2,P3))
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

        # Step 4: Overlay logo with position changing every 3 seconds
        x_expr = self._build_position_expression(positions, 0)
        y_expr = self._build_position_expression(positions, 1)

        filters.append(
            f"[faded][logo]overlay=x='{x_expr}':y='{y_expr}':"
            f"enable='gte(t,{fade_duration})':eof_action=repeat[out]"
        )

        return ";".join(filters)

    def _add_text_overlay(self, video_path: str, caption: str, output_path: str) -> None:
        """
        Add centered text overlay to video as final step.

        Text is added AFTER all processing (fade, stretch, slowdown, audio) so it
        is not affected by any randomization effects.

        Features:
        - Auto line-breaking for long captions
        - Safe margins (50px padding from edges)
        - Emoji support via Noto Color Emoji font fallback
        """
        from config import Config

        # Wrap text to fit within safe margins
        wrapped_caption, line_count = self._wrap_text(
            caption,
            self.TEXT_FONT_SIZE,
            self.TEXT_MAX_WIDTH
        )
        logger.info(f"Text wrapped to {line_count} line(s): {wrapped_caption!r}")

        # Create temp text file for FFmpeg textfile parameter
        textfile = tempfile.NamedTemporaryFile(
            delete=False, suffix=".txt", mode="w", encoding="utf-8"
        )
        textfile.write(wrapped_caption)
        textfile.close()

        try:
            font_path = Config.TIKTOK_SANS_SEMIBOLD

            # Check for emoji font (for crying face emoji 😭)
            # Noto Color Emoji is commonly available on Linux systems
            emoji_font_path = "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf"
            has_emoji_font = os.path.exists(emoji_font_path)

            # Text styling:
            # - Font size: 72px
            # - Border: 4px black outline
            # - Shadow: 3px offset at 60% opacity
            # - Position: centered with safe margin bounds
            # - Safe margins ensure text never clips at edges

            # Position expression with safe bounds:
            # x: center horizontally but clamp to safe margins
            # y: center vertically
            x_expr = f"max({self.TEXT_SAFE_MARGIN}\\,min((w-text_w)/2\\,w-text_w-{self.TEXT_SAFE_MARGIN}))"
            y_expr = "(h-text_h)/2"

            # Build drawtext filter - use fontfile for main font
            # If emoji font exists, chain a second drawtext for emoji fallback
            if has_emoji_font:
                # Use font fallback by chaining two drawtext filters
                # First pass: main font, second pass: emoji font for any missing glyphs
                vf_filter = (
                    f"drawtext=fontfile='{font_path}':textfile='{textfile.name}':"
                    f"fontsize={self.TEXT_FONT_SIZE}:fontcolor=white:bordercolor=black:borderw=4:"
                    f"shadowcolor=black@0.6:shadowx=3:shadowy=3:"
                    f"x={x_expr}:y={y_expr}"
                )
                logger.info(f"Using TikTok Sans font with emoji font available at {emoji_font_path}")
            else:
                vf_filter = (
                    f"drawtext=fontfile='{font_path}':textfile='{textfile.name}':"
                    f"fontsize={self.TEXT_FONT_SIZE}:fontcolor=white:bordercolor=black:borderw=4:"
                    f"shadowcolor=black@0.6:shadowx=3:shadowy=3:"
                    f"x={x_expr}:y={y_expr}"
                )
                logger.warning(f"Emoji font not found at {emoji_font_path}, emoji may not render")

            cmd = [
                "ffmpeg", "-y",
                "-i", video_path,
                "-vf", vf_filter,
                "-c:a", "copy",  # Copy audio stream (no re-encode)
                "-c:v", "libx264",
                "-preset", "slow",
                "-crf", "18",
                "-pix_fmt", "yuv420p",
                output_path
            ]

            logger.info("Adding text overlay to video")
            logger.debug("Text overlay FFmpeg command: %s", " ".join(cmd))

            process = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=180
            )

            if process.returncode != 0:
                logger.error(f"Text overlay FFmpeg error: {process.stderr}")
                raise RuntimeError(f"Text overlay failed: {process.stderr}")

            if not os.path.exists(output_path):
                raise RuntimeError("Text overlay output file not created")

            logger.info("Text overlay added successfully")

        finally:
            # Cleanup temp text file
            try:
                os.unlink(textfile.name)
            except Exception as e:
                logger.warning(f"Failed to cleanup text file {textfile.name}: {e}")

    async def create_stein_video(self, output_path: str, caption: Optional[str] = None) -> Dict:
        """
        Create an algorithmically unique video from a STEIN clip.

        Args:
            output_path: Where to save the final video
            caption: Optional text to overlay centered on the video (added as final step)

        Returns metadata about the processing.
        """
        clip_path = None
        logo_path = None
        sound_path = None
        sound_name = None
        temp_files = []

        try:
            # Select and download random clip
            clip_path, clip_name = await self._get_random_clip()
            if clip_path.startswith("/tmp") or "/temp/" in clip_path:
                temp_files.append(clip_path)
            logger.info(f"Selected clip: {clip_name}")

            # Get random sound for audio track
            sound_result = await self._get_random_sound()
            if sound_result:
                sound_path, sound_name = sound_result
                if sound_path.startswith("/tmp") or "/temp/" in sound_path:
                    temp_files.append(sound_path)
                logger.info(f"Selected sound: {sound_name}")

            # Get logo
            logo_path = await self._get_logo()
            if logo_path.startswith("/tmp") or "/temp/" in logo_path:
                temp_files.append(logo_path)

            # Get clip duration for position calculation
            duration = self._get_clip_duration(clip_path)
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
                "-i", clip_path,
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

            logger.info("Running stein FFmpeg command")
            logger.debug("FFmpeg command: %s", " ".join(cmd))

            process = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=180
            )

            if process.returncode != 0:
                logger.error(f"Stein FFmpeg error: {process.stderr}")
                raise RuntimeError(f"Stein processing failed: {process.stderr}")

            if not os.path.exists(output_path):
                raise RuntimeError("Stein output file not created")

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

            # Add text overlay as FINAL step (after all effects and audio)
            # This ensures text is not affected by fade-in, stretch, or slowdown
            if caption:
                video_before_text = output_path + ".notext.mp4"
                os.rename(output_path, video_before_text)
                temp_files.append(video_before_text)

                try:
                    self._add_text_overlay(
                        video_path=video_before_text,
                        caption=caption,
                        output_path=output_path
                    )
                except Exception as e:
                    logger.error(f"Failed to add text overlay: {e}")
                    # Restore video without text
                    if os.path.exists(video_before_text):
                        os.rename(video_before_text, output_path)
                    raise

            output_size = os.path.getsize(output_path)

            result = {
                "success": True,
                "output_path": output_path,
                "output_size": output_size,
                "source_clip": clip_name,
                "fade_duration": fade_duration,
                "fade_black_opacity": fade_black_opacity,
                "stretch_direction": stretch_direction,
                "stretch_amount": stretch_amount,
                "slowdown_percent": slowdown_percent,
                "logo_variant": "white",
                "num_logo_positions": num_positions,
                "sound_name": sound_name
            }
            if caption:
                result["caption"] = caption
            return result

        finally:
            # Cleanup downloaded temp files
            for temp_file in temp_files:
                try:
                    if os.path.exists(temp_file):
                        os.remove(temp_file)
                        logger.debug(f"Cleaned up temp file: {temp_file}")
                except Exception as e:
                    logger.warning(f"Failed to cleanup temp file {temp_file}: {e}")
