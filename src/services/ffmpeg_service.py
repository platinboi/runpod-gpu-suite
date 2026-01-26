"""
FFmpeg service for adding text overlays to images and videos
"""
import subprocess
import os
import tempfile
import re
import logging
from pathlib import Path
from typing import Dict, Any, Optional, Tuple, List
from config import Config, TextStyle, get_template
from models.schemas import TextOverrideOptions, sanitize_unicode

logger = logging.getLogger(__name__)

# Base resolution for font size scaling (1080p width)
# Font sizes in templates are designed for 1080p and will be scaled proportionally
BASE_RESOLUTION_WIDTH = 1080


class FFmpegService:
    """Handles FFmpeg text overlay operations"""

    @staticmethod
    def check_ffmpeg_available() -> bool:
        """Check if FFmpeg is installed and available"""
        try:
            result = subprocess.run(
                ['ffmpeg', '-version'],
                capture_output=True,
                text=True,
                timeout=5
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    @staticmethod
    def check_font_available(font_path: str) -> bool:
        """Check if font file exists"""
        return os.path.exists(font_path)

    @staticmethod
    def add_text_overlay(
        input_path: str,
        output_path: str,
        text: str,
        template_name: str = "default",
        overrides: Optional[TextOverrideOptions] = None,
        apply_fade_out: bool = False,
        fade_out_duration: float = 2.5
    ) -> Dict[str, Any]:
        """
        Add text overlay to video or image

        Args:
            input_path: Path to input file
            output_path: Path to output file
            text: Text to overlay
            template_name: Name of style template to use
            overrides: Optional style overrides
            apply_fade_out: Whether to hide text in the final seconds
            fade_out_duration: Seconds before end to hide text (default 2.5)

        Returns:
            Dict with status and details
        """
        try:
            # Normalize invisible/control newline variants so FFmpeg drawtext doesn't render them as BOX glyphs.
            text = sanitize_unicode(text)

            # Get base template
            style = get_template(template_name)

            # Apply overrides if provided
            if overrides:
                style = FFmpegService._apply_overrides(style, overrides)

            # Get media dimensions for text wrapping
            media_info = FFmpegService.get_media_info(input_path)
            img_width = FFmpegService._get_video_width(media_info)
            logger.info(f"[TEXT WRAP DEBUG] img_width from media: {img_width}")

            # Calculate scaled font size based on video resolution
            # This ensures consistent visual appearance across different resolutions
            if img_width:
                scale_factor = img_width / BASE_RESOLUTION_WIDTH
                scaled_font_size = int(style.font_size * scale_factor)
                logger.info(f"[FONT SCALING] Original font_size={style.font_size}, video_width={img_width}, scale_factor={scale_factor:.3f}, scaled_font_size={scaled_font_size}")
            else:
                # Fallback to original font size if width cannot be determined
                scaled_font_size = style.font_size
                logger.warning(f"[FONT SCALING] Could not determine video width, using original font_size={style.font_size}")

            # Wrap text if max_text_width_percent is specified (override or template default)
            max_text_width = overrides.max_text_width_percent if (overrides and overrides.max_text_width_percent) else style.max_text_width_percent
            logger.info(f"[TEXT WRAP DEBUG] max_text_width_percent: override={overrides.max_text_width_percent if overrides else None}, style={style.max_text_width_percent}, final={max_text_width}")

            if max_text_width and img_width:
                logger.info(f"[TEXT WRAP DEBUG] Condition passed! Wrapping text to {max_text_width}% of {img_width}px")
                text = FFmpegService._wrap_text(
                    text,
                    scaled_font_size,
                    style.font_path,
                    img_width,
                    max_text_width
                )
                logger.info(f"[TEXT WRAP DEBUG] Wrapped text result:\n{text}")
            else:
                logger.warning(f"[TEXT WRAP DEBUG] Condition FAILED! max_text_width={max_text_width}, img_width={img_width} - text wrapping SKIPPED")

            # Extract video duration if text hiding is requested
            video_duration = None
            if apply_fade_out:
                if 'format' in media_info and 'duration' in media_info['format']:
                    try:
                        video_duration = float(media_info['format']['duration'])
                        logger.info(f"Extracted video duration for text hiding: {video_duration}s")
                    except (ValueError, TypeError) as e:
                        logger.warning(f"Failed to parse video duration for text hiding: {e}")
                        apply_fade_out = False
                else:
                    logger.warning("Video duration not available, skipping text hiding")
                    apply_fade_out = False

            # Write text to temp file for FFmpeg textfile parameter
            # Using textfile= instead of text= bypasses FFmpeg multiline rendering bugs
            text_file_path = FFmpegService._write_text_file(text)
            logger.info(f"Created temp text file for FFmpeg: {text_file_path}")

            try:
                # Build FFmpeg filter using textfile path
                filter_str = FFmpegService._build_drawtext_filter(
                    text_file_path,
                    style,
                    overrides,
                    scaled_font_size=scaled_font_size,
                    fade_out_duration=fade_out_duration if apply_fade_out else None,
                    video_duration=video_duration if apply_fade_out else None
                )

                # Determine if input is image or video
                is_image = FFmpegService._is_image(input_path)

                # Build FFmpeg command
                cmd = FFmpegService._build_ffmpeg_command(
                    input_path, output_path, filter_str, is_image
                )

                logger.info(f"Running FFmpeg command: {' '.join(cmd)}")

                # Execute FFmpeg
                process = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=120  # 2 minute timeout
                )

                if process.returncode != 0:
                    logger.error(f"FFmpeg error: {process.stderr}")
                    raise Exception(f"FFmpeg processing failed: {process.stderr}")

                # Verify output file was created
                if not os.path.exists(output_path):
                    raise Exception("Output file was not created")

                output_size = os.path.getsize(output_path)
                logger.info(f"Successfully created output file: {output_path} ({output_size} bytes)")

                return {
                    "success": True,
                    "status": "success",
                    "output_path": output_path,
                    "output_size": output_size
                }

            except subprocess.TimeoutExpired:
                raise Exception("FFmpeg processing timed out (max 2 minutes)")

            finally:
                # Clean up temp text file
                if os.path.exists(text_file_path):
                    try:
                        os.remove(text_file_path)
                        logger.debug(f"Cleaned up temp text file: {text_file_path}")
                    except Exception as cleanup_err:
                        logger.warning(f"Failed to clean up temp text file {text_file_path}: {cleanup_err}")

        except Exception as e:
            logger.error(f"Error adding text overlay: {str(e)}")
            raise

    @staticmethod
    def _apply_overrides(style: TextStyle, overrides: TextOverrideOptions) -> TextStyle:
        """Apply override options to base style"""
        # Create a copy of the style
        override_dict = overrides.model_dump(exclude_none=True)

        # Handle font weight override (preferred method)
        if 'font_weight' in override_dict:
            font_weight = override_dict.pop('font_weight')
            # Map numeric weight to available TikTok Sans fonts
            # 100-449 → Medium (500), 450-900 → SemiBold (600)
            if font_weight < 450:
                style.font_path = Config.TIKTOK_SANS_MEDIUM
            else:
                style.font_path = Config.TIKTOK_SANS_SEMIBOLD
        # Handle legacy font_family override (deprecated)
        elif 'font_family' in override_dict:
            font_family = override_dict.pop('font_family')
            if font_family == 'bold':
                style.font_path = Config.INTER_BOLD
            else:
                style.font_path = Config.INTER_REGULAR

        # Apply other overrides
        for key, value in override_dict.items():
            if hasattr(style, key):
                setattr(style, key, value)

        return style

    @staticmethod
    def _escape_ffmpeg_text(text: str) -> str:
        """
        Escape text for FFmpeg drawtext filter's text parameter.
        FFmpeg uses : and \\ as special chars, and supports \\n for line breaks.

        Args:
            text: Text to escape

        Returns:
            Escaped text safe for FFmpeg's text parameter
        """
        # Remove carriage returns (Windows \r\n line endings leave \r after split by \n)
        text = text.replace('\r', '')
        # Escape backslashes first (must be done before other escapes)
        text = text.replace('\\', '\\\\')
        # Escape colons (FFmpeg uses : as parameter separator)
        text = text.replace(':', '\\:')
        # Escape single quotes for shell safety
        text = text.replace("'", "'\\\\\\''")
        # Newlines are kept as-is - FFmpeg interprets \\n as line breaks in text parameter
        return text

    @staticmethod
    def _write_text_file(text: str, temp_dir: str = None) -> str:
        """
        Write text to temp file for FFmpeg textfile parameter.
        ZERO preprocessing - matches working outfit_service.py exactly.
        Preprocessing CAUSES BOX symbols, not fixes them!
        """
        tmp = tempfile.NamedTemporaryFile(
            delete=False,
            suffix=".txt",
            mode="w",
            encoding="utf-8"
        )
        tmp.write(text)
        tmp.flush()
        tmp.close()
        return tmp.name

    @staticmethod
    def _build_drawtext_filter(
        textfile_path: str,
        style: TextStyle,
        overrides: Optional[TextOverrideOptions] = None,
        scaled_font_size: Optional[int] = None,
        fade_out_duration: Optional[float] = None,
        video_duration: Optional[float] = None
    ) -> str:
        """
        Build FFmpeg drawtext filter - EXACT copy of outfit_service.py pattern.
        Uses NAMED colors (white, black) and single f-string construction.
        """
        x, y = FFmpegService._calculate_position(style, overrides)
        font_size = scaled_font_size if scaled_font_size is not None else style.font_size

        # Build EXACTLY like outfit_service.py - single f-string, NAMED colors, NO hex
        # This is the ONLY pattern that works for multiline text without BOX symbols
        filter_str = (
            f"drawtext=fontfile='{style.font_path}':textfile='{textfile_path}':"
            f"fontsize={font_size}:fontcolor=white:bordercolor=black:borderw={style.border_width}:"
            f"shadowcolor=black@0.6:shadowx={style.shadow_x}:shadowy={style.shadow_y}:"
            f"x={x}:y={y}"
        )

        # Add alpha for text disappearance if requested
        if fade_out_duration is not None and video_duration is not None:
            cutoff_time = video_duration - fade_out_duration
            # Insert alpha parameter before the closing
            filter_str = filter_str.replace(
                f":x={x}:y={y}",
                f":alpha='if(lt(t\\,{cutoff_time})\\,1\\,0)':x={x}:y={y}"
            )
            logger.info(f"Text will disappear at {cutoff_time}s (last {fade_out_duration}s hidden)")

        return filter_str

    @staticmethod
    def _calculate_position(
        style: TextStyle,
        overrides: Optional[TextOverrideOptions] = None
    ) -> Tuple[str, str]:
        """Calculate x, y position for text"""
        position = style.position
        if overrides and overrides.position:
            position = overrides.position

        # Position presets
        positions = {
            "center": ("(w-text_w)/2", "(h-text_h)/2"),
            "top-left": ("10", "10"),
            "top-right": ("w-text_w-10", "10"),
            "top-center": ("(w-text_w)/2", "10"),
            "bottom-left": ("10", "h-text_h-10"),
            "bottom-right": ("w-text_w-10", "h-text_h-10"),
            "bottom-center": ("(w-text_w)/2", "h-text_h-10"),
            "middle-left": ("10", "(h-text_h)/2"),
            "middle-right": ("w-text_w-10", "(h-text_h)/2"),
        }

        if position == "custom" and overrides:
            if overrides.custom_x is not None and overrides.custom_y is not None:
                return (str(overrides.custom_x), str(overrides.custom_y))

        return positions.get(position, positions["center"])

    @staticmethod
    def _convert_color(color: str) -> str:
        """Convert color name or hex to FFmpeg format"""
        color_map = {
            'white': '0xFFFFFF',
            'black': '0x000000',
            'red': '0xFF0000',
            'green': '0x00FF00',
            'blue': '0x0000FF',
            'yellow': '0xFFFF00',
            'cyan': '0x00FFFF',
            'magenta': '0xFF00FF',
            'orange': '0xFFA500',
            'purple': '0x800080',
            'pink': '0xFFC0CB',
            'gray': '0x808080',
            'grey': '0x808080'
        }

        color_lower = color.lower()
        if color_lower in color_map:
            return color_map[color_lower]

        # Handle hex colors
        if color.startswith('#'):
            return '0x' + color[1:]

        # Default to white if unknown
        return '0xFFFFFF'

    @staticmethod
    def _is_image(file_path: str) -> bool:
        """Check if file is an image based on extension"""
        image_extensions = {'.jpg', '.jpeg', '.png'}
        ext = Path(file_path).suffix.lower()
        return ext in image_extensions

    @staticmethod
    def _build_ffmpeg_command(
        input_path: str,
        output_path: str,
        filter_str: str,
        is_image: bool
    ) -> list:
        """Build complete FFmpeg command using filter_complex (matches outfit_service)"""
        cmd = ['ffmpeg', '-y', '-i', input_path]

        # Use -filter_complex instead of -vf to match outfit_service
        # This fixes BOX symbols appearing at end of lines in multiline text
        filter_complex = f"[0:v]{filter_str}[vout]"

        if is_image:
            # For images, use filter_complex for consistent text rendering
            cmd.extend([
                '-filter_complex', filter_complex,
                '-map', '[vout]',
                '-q:v', '2',  # High quality
                output_path
            ])
        else:
            # For videos, use filter_complex and preserve audio
            cmd.extend([
                '-filter_complex', filter_complex,
                '-map', '[vout]',
                '-map', '0:a?',  # Map audio if exists (? = optional, won't fail if no audio)
                '-c:v', 'h264_nvenc',  # NVIDIA GPU encoder
                '-preset', 'p4',  # NVENC quality preset (p1=fastest, p7=slowest/best)
                '-cq', '18',  # Constant quality mode (lower = better quality)
                '-c:a', 'aac',  # AAC audio codec
                '-b:a', '192k',  # Audio bitrate (higher quality audio)
                '-movflags', '+faststart',  # Enable streaming
                output_path
            ])

        return cmd

    @staticmethod
    def get_media_info(file_path: str) -> Dict[str, Any]:
        """Get basic media information using ffprobe"""
        try:
            cmd = [
                'ffprobe',
                '-v', 'quiet',
                '-print_format', 'json',
                '-show_format',
                '-show_streams',
                file_path
            ]

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

            if result.returncode == 0:
                import json
                return json.loads(result.stdout)
            else:
                logger.error(f"ffprobe failed for {file_path}: {result.stderr}")
                return {}

        except Exception as e:
            logger.warning(f"Failed to get media info: {str(e)}")
            return {}

    @staticmethod
    def _get_video_width(media_info: Dict[str, Any]) -> Optional[int]:
        """Extract video/image width from media info"""
        try:
            if 'streams' in media_info:
                for stream in media_info['streams']:
                    if stream.get('codec_type') == 'video' and 'width' in stream:
                        return int(stream['width'])
            return None
        except Exception as e:
            logger.warning(f"Failed to extract video width: {str(e)}")
            return None

    @staticmethod
    def _get_video_height(media_info: Dict[str, Any]) -> Optional[int]:
        """Extract video/image height from media info"""
        try:
            if 'streams' in media_info:
                for stream in media_info['streams']:
                    if stream.get('codec_type') == 'video' and 'height' in stream:
                        return int(stream['height'])
            return None
        except Exception as e:
            logger.warning(f"Failed to extract video height: {str(e)}")
            return None

    @staticmethod
    def _wrap_text(
        text: str,
        font_size: int,
        font_path: str,
        img_width: int,
        max_width_percent: int
    ) -> str:
        """
        Wrap text using textwrap.wrap() - matches working outfit_service pattern.
        NO preprocessing - that causes BOX symbols!
        """
        import textwrap

        if not text:
            return ""

        max_width_px = (img_width * max_width_percent) / 100
        avg_char_px = max(font_size * 0.55, 1)
        max_chars = max(1, int(max_width_px / avg_char_px))

        logger.info(f"[TEXT WRAP] max_width_px={max_width_px}, avg_char_px={avg_char_px}, max_chars={max_chars}")

        lines = textwrap.wrap(text, width=max_chars)
        if not lines:
            return ""
        return "\n".join(lines)

    async def trim_video(
        self,
        input_path: str,
        output_path: str,
        target_duration: float,
        trim_mode: str = "both"
    ) -> Dict[str, Any]:
        """
        Trim a video to a target duration.

        Args:
            input_path: Path to input video
            output_path: Path to output trimmed video
            target_duration: Desired duration in seconds
            trim_mode: 'start' (cut from beginning), 'end' (cut from end), 'both' (split equally)

        Returns:
            Dict with success status and new duration
        """
        import asyncio

        # Get original duration (get_media_info is synchronous)
        media_info = self.get_media_info(input_path)
        original_duration = float(media_info['format']['duration'])

        # Validate: can't extend, only trim
        if target_duration >= original_duration:
            logger.info(f"Target duration {target_duration}s >= original {original_duration}s, skipping trim")
            return {"trimmed": False, "duration": original_duration}

        # Calculate trim amounts
        trim_total = original_duration - target_duration

        if trim_mode == "start":
            start_time = trim_total
            end_time = original_duration
        elif trim_mode == "end":
            start_time = 0
            end_time = target_duration
        else:  # "both"
            start_time = trim_total / 2
            end_time = original_duration - (trim_total / 2)

        # FFmpeg trim command with accurate seeking (-ss after -i)
        cmd = [
            'ffmpeg', '-y',
            '-i', input_path,
            '-ss', str(start_time),
            '-to', str(end_time),
            '-c:v', 'h264_nvenc',  # NVIDIA GPU encoder
            '-preset', 'p4',
            '-cq', '18',
            '-an',  # No audio (consistent with merge pipeline)
            output_path
        ]

        logger.info(f"Trimming video: {original_duration:.2f}s → {target_duration:.2f}s (mode={trim_mode}, start={start_time:.2f}s, end={end_time:.2f}s)")

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await process.communicate()

        if process.returncode != 0:
            raise RuntimeError(f"FFmpeg trim failed: {stderr.decode()}")

        logger.info(f"Successfully trimmed video to {target_duration}s")
        return {"trimmed": True, "duration": target_duration, "original_duration": original_duration}

    @staticmethod
    def merge_videos(
        input_paths: List[str],
        output_path: str
    ) -> Dict[str, Any]:
        """
        Merge multiple video files into a single video using FFmpeg concat filter

        Args:
            input_paths: List of paths to video files to merge
            output_path: Path for the merged output file

        Returns:
            Dict with success status and metadata

        Raises:
            Exception: If merge fails or input validation fails
        """
        try:
            if len(input_paths) < 2:
                raise ValueError("At least 2 videos are required for merging")

            # Verify all input files exist
            for path in input_paths:
                if not os.path.exists(path):
                    raise FileNotFoundError(f"Input file not found: {path}")

            logger.info(f"Merging {len(input_paths)} videos into {output_path}")

            # Normalize fps and pixel format before concat to prevent timestamp issues
            # Different frame rates between clips cause corrupted playback
            normalize_filters = []
            normalized_inputs = []
            for i in range(len(input_paths)):
                normalize_filters.append(f"[{i}:v]fps=30,format=yuv420p[v{i}]")
                normalized_inputs.append(f"[v{i}]")

            concat_filter = ";".join(normalize_filters) + ";" + "".join(normalized_inputs) + f"concat=n={len(input_paths)}:v=1:a=0[v]"
            map_args = ['-map', '[v]']
            logger.info("Using video-only concat with fps/format normalization")

            # Build FFmpeg command
            cmd = ['ffmpeg', '-y']

            # Add all input files
            for input_path in input_paths:
                cmd.extend(['-i', input_path])

            # Add filter_complex and output settings
            cmd.extend([
                '-filter_complex', concat_filter,
                *map_args,
                '-c:v', 'h264_nvenc',  # NVIDIA GPU encoder
                '-preset', 'p4',  # NVENC quality preset (p1=fastest, p7=slowest/best)
                '-cq', '18',  # Constant quality mode (lower = better quality)
            ])

            cmd.extend([
                '-movflags', '+faststart',  # Enable streaming
                output_path
            ])

            logger.info(f"Running FFmpeg merge command: {' '.join(cmd)}")

            # Execute FFmpeg
            process = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=Config.MERGE_TIMEOUT  # Configurable timeout for merging
            )

            if process.returncode != 0:
                logger.error(f"FFmpeg merge error: {process.stderr}")
                raise Exception(f"FFmpeg merge failed: {process.stderr}")

            # Verify output file was created
            if not os.path.exists(output_path):
                raise Exception("Merged output file was not created")

            output_size = os.path.getsize(output_path)

            # Get output video duration
            media_info = FFmpegService.get_media_info(output_path)
            duration = None
            if 'format' in media_info and 'duration' in media_info['format']:
                duration = float(media_info['format']['duration'])

            logger.info(f"Successfully merged {len(input_paths)} videos: {output_path} ({output_size} bytes, {duration}s)")

            return {
                "success": True,
                "output_path": output_path,
                "output_size": output_size,
                "duration": duration,
                "clips_merged": len(input_paths)
            }

        except subprocess.TimeoutExpired:
            timeout_mins = Config.MERGE_TIMEOUT / 60
            raise Exception(f"FFmpeg merge timed out (max {timeout_mins:.0f} minutes)")
        except Exception as e:
            logger.error(f"Error merging videos: {str(e)}")
            raise

    @staticmethod
    def scale_video(
        input_path: str,
        output_path: str,
        target_width: int,
        target_height: int
    ) -> Dict[str, Any]:
        """
        Scale a video to target resolution with aspect ratio preservation and padding

        Args:
            input_path: Path to input video
            output_path: Path to save scaled video
            target_width: Target width in pixels
            target_height: Target height in pixels

        Returns:
            Dictionary with success status and output info

        Raises:
            Exception: If scaling fails
        """
        try:
            if not os.path.exists(input_path):
                raise FileNotFoundError(f"Input file not found: {input_path}")

            logger.info(f"Scaling video {input_path} to {target_width}x{target_height}")

            # Get current video dimensions
            media_info = FFmpegService.get_media_info(input_path)
            current_width = FFmpegService._get_video_width(media_info)
            current_height = FFmpegService._get_video_height(media_info)

            if current_width == target_width and current_height == target_height:
                # Already correct size - just copy
                logger.info(f"Video already at target resolution, copying: {input_path}")
                import shutil
                shutil.copy2(input_path, output_path)
                return {
                    "success": True,
                    "output_path": output_path,
                    "scaled": False
                }

            # Build FFmpeg command with scale + pad filters
            # This maintains aspect ratio and centers video with black bars
            filter_str = (
                f"scale={target_width}:{target_height}:force_original_aspect_ratio=decrease,"
                f"pad={target_width}:{target_height}:(ow-iw)/2:(oh-ih)/2"
            )

            cmd = [
                'ffmpeg', '-y',
                '-i', input_path,
                '-vf', filter_str,
                '-c:v', 'h264_nvenc',  # NVIDIA GPU encoder
                '-preset', 'p4',
                '-cq', '23',  # Quality setting
                '-c:a', 'copy',  # Copy audio without re-encoding
                '-movflags', '+faststart',
                output_path
            ]

            logger.info(f"Running FFmpeg scale command: {' '.join(cmd)}")

            # Execute FFmpeg
            process = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120  # 2 minute timeout
            )

            if process.returncode != 0:
                logger.error(f"FFmpeg scale error: {process.stderr}")
                raise Exception(f"FFmpeg scale failed: {process.stderr}")

            # Verify output file was created
            if not os.path.exists(output_path):
                raise Exception("Scaled output file was not created")

            output_size = os.path.getsize(output_path)
            logger.info(f"Successfully scaled video: {output_path} ({output_size} bytes)")

            return {
                "success": True,
                "output_path": output_path,
                "output_size": output_size,
                "scaled": True
            }

        except subprocess.TimeoutExpired:
            raise Exception("FFmpeg scaling timed out (max 2 minutes)")
        except Exception as e:
            logger.error(f"Error scaling video: {str(e)}")
            raise

    @staticmethod
    def add_audio_track(
        video_path: str,
        audio_path: str,
        output_path: str
    ) -> Dict[str, Any]:
        """
        Add an audio track to a video file.

        Uses stream copy for video (fast, no re-encoding) and AAC for audio.
        The output duration matches the video length (-shortest).

        Args:
            video_path: Path to input video (no audio or audio will be replaced)
            audio_path: Path to audio file (MP3, AAC, etc.)
            output_path: Path for output video with audio

        Returns:
            Dict with success status and output info

        Raises:
            Exception: If adding audio fails
        """
        try:
            if not os.path.exists(video_path):
                raise FileNotFoundError(f"Video file not found: {video_path}")
            if not os.path.exists(audio_path):
                raise FileNotFoundError(f"Audio file not found: {audio_path}")

            logger.info(f"Adding audio track to video: {video_path}")

            cmd = [
                'ffmpeg', '-y',
                '-i', video_path,
                '-i', audio_path,
                '-map', '0:v',      # Take video from first input
                '-map', '1:a',      # Take audio from second input
                '-c:v', 'copy',     # Copy video stream (no re-encode, fast)
                '-c:a', 'aac',      # Encode audio as AAC
                '-b:a', '192k',     # Audio bitrate
                '-shortest',        # End when video ends
                '-movflags', '+faststart',
                output_path
            ]

            logger.info(f"Running FFmpeg add_audio command: {' '.join(cmd)}")

            process = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120  # 2 minute timeout
            )

            if process.returncode != 0:
                logger.error(f"FFmpeg add_audio error: {process.stderr}")
                raise Exception(f"FFmpeg add_audio failed: {process.stderr}")

            if not os.path.exists(output_path):
                raise Exception("Output file with audio was not created")

            output_size = os.path.getsize(output_path)
            logger.info(f"Successfully added audio: {output_path} ({output_size} bytes)")

            return {
                "success": True,
                "output_path": output_path,
                "output_size": output_size
            }

        except subprocess.TimeoutExpired:
            raise Exception("FFmpeg add_audio timed out (max 2 minutes)")
        except Exception as e:
            logger.error(f"Error adding audio track: {str(e)}")
            raise
