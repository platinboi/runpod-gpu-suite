"""
Service for merging multiple video clips with text overlays
"""
import asyncio
import os
import uuid
import logging
from typing import List, Dict, Tuple, Optional
from config import Config
from services.download_service import DownloadService
from services.ffmpeg_service import FFmpegService
from models.schemas import TextOverrideOptions

logger = logging.getLogger(__name__)


class MergeService:
    """Handles downloading, processing, and merging multiple video clips"""

    def __init__(self):
        self.download_service = DownloadService()
        self.ffmpeg_service = FFmpegService()

    async def download_clips(self, clip_urls: List[str]) -> List[Tuple[str, str]]:
        """
        Download multiple clips in parallel

        Args:
            clip_urls: List of URLs to download

        Returns:
            List of tuples (file_path, content_type)

        Raises:
            Exception: If any download fails
        """
        logger.info(f"Downloading {len(clip_urls)} clips in parallel")

        # Download all clips concurrently
        download_tasks = [
            self.download_service.download_from_url(url)
            for url in clip_urls
        ]

        try:
            results = await asyncio.gather(*download_tasks)
            logger.info(f"Successfully downloaded {len(results)} clips")
            return results
        except Exception as e:
            logger.error(f"Failed to download clips: {str(e)}")
            raise Exception(f"Clip download failed: {str(e)}")

    def scale_clips_to_target(
        self,
        downloaded_clips: List[Tuple[str, str]]
    ) -> Tuple[List[str], int, int]:
        """
        Scale all clips to match the first clip's resolution

        Args:
            downloaded_clips: List of tuples (file_path, content_type)

        Returns:
            Tuple of (scaled_clip_paths, target_width, target_height)

        Raises:
            Exception: If scaling fails
        """
        if not downloaded_clips:
            raise ValueError("No clips to scale")

        scaled_paths = []

        try:
            # Get target resolution from first clip
            first_clip_path = downloaded_clips[0][0]

            # Verify file exists before probing
            if not os.path.exists(first_clip_path):
                raise FileNotFoundError(f"First clip file not found: {first_clip_path}")

            media_info = self.ffmpeg_service.get_media_info(first_clip_path)

            # Check if probe succeeded
            if not media_info or 'streams' not in media_info:
                raise ValueError(
                    f"Could not probe first clip. File may be corrupted or invalid. "
                    f"Path: {first_clip_path}"
                )

            target_width = self.ffmpeg_service._get_video_width(media_info)
            target_height = self.ffmpeg_service._get_video_height(media_info)

            if target_width is None or target_height is None:
                raise ValueError(
                    f"Could not determine resolution of first clip. "
                    f"Path: {first_clip_path}, "
                    f"Media info: {media_info.get('streams', [])[:1]}"
                )

            logger.info(f"Target resolution from first clip: {target_width}x{target_height}")

            # Scale each clip to target resolution
            for i, (clip_path, content_type) in enumerate(downloaded_clips):
                logger.info(f"Scaling clip {i+1}/{len(downloaded_clips)} to {target_width}x{target_height}")

                # Generate output path for scaled clip
                output_filename = f"scaled_{uuid.uuid4()}.mp4"
                output_path = os.path.join(Config.TEMP_DIR, output_filename)

                # Scale video (or copy if already correct size)
                result = self.ffmpeg_service.scale_video(
                    input_path=clip_path,
                    output_path=output_path,
                    target_width=target_width,
                    target_height=target_height
                )

                if not result.get('success'):
                    raise Exception(f"Failed to scale clip {i+1}")

                scaled_paths.append(output_path)
                logger.info(f"Clip {i+1}: {'Scaled' if result.get('scaled') else 'Copied'} to {output_path}")

            logger.info(f"Successfully scaled {len(scaled_paths)} clips to {target_width}x{target_height}")
            return scaled_paths, target_width, target_height

        except Exception as e:
            # Cleanup any partially scaled files
            for path in scaled_paths:
                self.cleanup_file(path)
            logger.error(f"Scaling failed: {str(e)}")
            raise Exception(f"Clip scaling failed: {str(e)}")

    def apply_overlays_to_clips(
        self,
        clip_configs: List[Dict],
        scaled_clip_paths: List[str]
    ) -> List[str]:
        """
        Apply text overlays to each scaled clip

        Args:
            clip_configs: List of clip configurations with text/template/overrides
            scaled_clip_paths: List of paths to scaled video files

        Returns:
            List of paths to overlayed clip files

        Raises:
            Exception: If overlay processing fails
        """
        overlayed_paths = []

        try:
            for i, (clip_path, config) in enumerate(zip(scaled_clip_paths, clip_configs)):
                logger.info(f"Applying overlay to clip {i+1}/{len(clip_configs)}: {config.get('text')}")

                # Generate output path for overlayed clip
                output_filename = f"overlayed_{uuid.uuid4()}.mp4"
                output_path = os.path.join(Config.TEMP_DIR, output_filename)

                # Parse overrides if provided
                overrides = None
                if config.get('overrides'):
                    try:
                        overrides = TextOverrideOptions(**config['overrides'])
                    except Exception as e:
                        logger.warning(f"Failed to parse overrides for clip {i+1}: {e}")

                # Detect if this is the last clip - hide text in final seconds only for last clip
                is_last_clip = (i == len(clip_configs) - 1)
                if is_last_clip:
                    logger.info(f"Last clip detected - text will disappear in final 2.5 seconds (clip {i+1})")

                # Apply text overlay using FFmpeg service
                result = self.ffmpeg_service.add_text_overlay(
                    input_path=clip_path,
                    output_path=output_path,
                    text=config['text'],
                    template_name=config.get('template', 'default'),
                    overrides=overrides,
                    apply_fade_out=is_last_clip
                )

                if not result.get('success'):
                    raise Exception(f"Failed to apply overlay to clip {i+1}")

                overlayed_paths.append(output_path)
                logger.info(f"Successfully overlayed clip {i+1}: {output_path}")

            return overlayed_paths

        except Exception as e:
            # Cleanup any partially processed files
            for path in overlayed_paths:
                self.cleanup_file(path)
            raise Exception(f"Overlay processing failed: {str(e)}")

    def merge_clips(self, overlayed_paths: List[str], output_path: str) -> Dict:
        """
        Merge multiple overlayed clips into a single video

        Args:
            overlayed_paths: List of paths to overlayed clip files
            output_path: Path for the merged output file

        Returns:
            Dict with merge metadata

        Raises:
            Exception: If merge fails
        """
        logger.info(f"Merging {len(overlayed_paths)} clips into {output_path}")

        try:
            # Use FFmpeg service's merge_videos method
            result = self.ffmpeg_service.merge_videos(
                input_paths=overlayed_paths,
                output_path=output_path
            )

            if not result.get('success'):
                raise Exception("FFmpeg merge failed")

            logger.info(f"Successfully merged {len(overlayed_paths)} clips")
            return result

        except Exception as e:
            logger.error(f"Merge failed: {str(e)}")
            raise Exception(f"Video merge failed: {str(e)}")

    def validate_merge_request(self, clip_configs: List[Dict]) -> None:
        """
        Validate merge request parameters

        Args:
            clip_configs: List of clip configurations

        Raises:
            ValueError: If validation fails
        """
        num_clips = len(clip_configs)

        # Check clip count
        if num_clips < 2:
            raise ValueError("At least 2 clips are required for merging")

        if num_clips > Config.MAX_MERGE_CLIPS:
            raise ValueError(f"Maximum {Config.MAX_MERGE_CLIPS} clips allowed per merge request")

        # Validate each clip config
        for i, config in enumerate(clip_configs):
            if not config.get('url'):
                raise ValueError(f"Clip {i+1}: URL is required")

            if not config.get('text'):
                raise ValueError(f"Clip {i+1}: Text is required")

            # Validate text length
            if len(config['text']) > 500:
                raise ValueError(f"Clip {i+1}: Text too long (max 500 characters)")

        logger.info(f"Validation passed for {num_clips} clips")

    @staticmethod
    def cleanup_file(file_path: str) -> None:
        """Delete a temporary file"""
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
                logger.debug(f"Cleaned up: {file_path}")
        except Exception as e:
            logger.warning(f"Failed to cleanup {file_path}: {str(e)}")

    @staticmethod
    def cleanup_files(file_paths: List[str]) -> None:
        """Delete multiple temporary files"""
        for path in file_paths:
            MergeService.cleanup_file(path)

    async def process_merge_request(
        self,
        clip_configs: List[Dict],
        output_path: str,
        first_clip_duration: Optional[float] = None,
        first_clip_trim_mode: str = "both"
    ) -> Dict:
        """
        Main entry point: Download, scale, overlay, and merge clips

        New workflow: Download → Trim (optional) → Scale → Overlay → Merge
        This ensures text overlays wrap correctly to target canvas dimensions

        Args:
            clip_configs: List of clip configurations
            output_path: Path for final merged output
            first_clip_duration: Optional target duration for first clip in seconds
            first_clip_trim_mode: Where to trim from: 'start', 'end', or 'both'

        Returns:
            Dict with processing metadata

        Raises:
            Exception: If any step fails
        """
        downloaded_paths = []
        scaled_paths = []
        overlayed_paths = []
        trimmed_path = None

        try:
            # Step 1: Validate request
            self.validate_merge_request(clip_configs)

            # Step 2: Download all clips
            clip_urls = [config['url'] for config in clip_configs]
            downloaded_clips = await self.download_clips(clip_urls)
            downloaded_paths = [path for path, _ in downloaded_clips]

            # Step 2.5: Trim first clip if requested
            if first_clip_duration is not None and len(downloaded_clips) > 0:
                first_clip_path, first_clip_type = downloaded_clips[0]
                trimmed_path = first_clip_path.replace('.mp4', '_trimmed.mp4')
                if not trimmed_path.endswith('.mp4'):
                    trimmed_path = first_clip_path + '_trimmed.mp4'

                trim_result = await self.ffmpeg_service.trim_video(
                    input_path=first_clip_path,
                    output_path=trimmed_path,
                    target_duration=first_clip_duration,
                    trim_mode=first_clip_trim_mode
                )

                if trim_result['trimmed']:
                    # Replace first clip with trimmed version
                    downloaded_clips[0] = (trimmed_path, first_clip_type)
                    # Clean up original untrimmed file immediately
                    self.cleanup_file(first_clip_path)
                    # Update downloaded_paths to include trimmed file for later cleanup
                    downloaded_paths[0] = trimmed_path
                    logger.info(f"First clip trimmed: {trim_result['original_duration']:.2f}s → {first_clip_duration}s (mode={first_clip_trim_mode})")
                else:
                    # Trimming was skipped, remove unused trimmed_path
                    trimmed_path = None

            # Step 3: Scale all clips to match first clip's resolution
            scaled_paths, target_width, target_height = self.scale_clips_to_target(downloaded_clips)
            logger.info(f"All clips scaled to target resolution: {target_width}x{target_height}")

            # Step 4: Cleanup downloaded originals (no longer needed)
            self.cleanup_files(downloaded_paths)
            downloaded_paths = []

            # Step 5: Apply overlays to scaled clips (text wraps to correct width)
            overlayed_paths = self.apply_overlays_to_clips(clip_configs, scaled_paths)

            # Step 6: Cleanup scaled clips (no longer needed)
            self.cleanup_files(scaled_paths)
            scaled_paths = []

            # Step 7: Merge all overlayed clips (no scaling needed - already same resolution)
            merge_result = self.merge_clips(overlayed_paths, output_path)

            # Step 8: Cleanup overlayed clips (no longer needed)
            self.cleanup_files(overlayed_paths)
            overlayed_paths = []

            return {
                'success': True,
                'clips_processed': len(clip_configs),
                'target_resolution': f"{target_width}x{target_height}",
                'output_path': output_path,
                **merge_result
            }

        except Exception as e:
            # Cleanup on failure
            self.cleanup_files(downloaded_paths)
            self.cleanup_files(scaled_paths)
            self.cleanup_files(overlayed_paths)

            logger.error(f"Merge request processing failed: {str(e)}")
            raise

