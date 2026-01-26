"""
Service for downloading files from URLs (primarily Cloudflare R2)
"""
import aiohttp
import asyncio
import os
from pathlib import Path
from typing import Tuple
from config import Config
import uuid
import logging

logger = logging.getLogger(__name__)


class DownloadService:
    """Handles downloading files from URLs"""

    @staticmethod
    async def download_from_url(url: str) -> Tuple[str, str]:
        """
        Download a file from a URL to temp directory

        Args:
            url: URL to download from

        Returns:
            Tuple of (local_file_path, content_type)

        Raises:
            Exception: If download fails
        """
        try:
            # Use configurable timeout for downloads
            timeout = aiohttp.ClientTimeout(total=Config.DOWNLOAD_TIMEOUT)  # Configurable download timeout

            # Add browser-like headers to bypass Cloudflare bot protection
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'video/mp4,video/*,*/*',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate, br',
                'Connection': 'keep-alive',
                'Referer': url,
            }

            async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
                async with session.get(url, allow_redirects=True) as response:
                    if response.status != 200:
                        raise Exception(f"Failed to download file: HTTP {response.status}")

                    # Get content type
                    content_type = response.headers.get('Content-Type', 'application/octet-stream')

                    # Validate content type
                    if not DownloadService._is_valid_content_type(content_type):
                        raise Exception(f"Invalid content type: {content_type}")

                    # Get file size from headers
                    content_length = response.headers.get('Content-Length')
                    if content_length and int(content_length) > Config.MAX_FILE_SIZE:
                        raise Exception(f"File too large: {content_length} bytes (max: {Config.MAX_FILE_SIZE})")

                    # Generate unique filename
                    file_extension = DownloadService._get_extension_from_content_type(content_type)
                    unique_filename = f"{uuid.uuid4()}{file_extension}"
                    file_path = os.path.join(Config.TEMP_DIR, unique_filename)

                    # Ensure temp directory exists
                    os.makedirs(Config.TEMP_DIR, exist_ok=True)

                    # Download file in chunks
                    total_size = 0
                    chunk_size = 1024 * 1024  # 1MB chunks

                    with open(file_path, 'wb') as f:
                        async for chunk in response.content.iter_chunked(chunk_size):
                            total_size += len(chunk)

                            # Check size limit during download
                            if total_size > Config.MAX_FILE_SIZE:
                                # Clean up partial file
                                f.close()
                                if os.path.exists(file_path):
                                    os.remove(file_path)
                                raise Exception(f"File exceeds maximum size: {Config.MAX_FILE_SIZE} bytes")

                            f.write(chunk)

                    logger.info(f"Downloaded {total_size} bytes from {url} to {file_path}")
                    return file_path, content_type

        except asyncio.TimeoutError:
            raise Exception(f"Download timed out after {Config.DOWNLOAD_TIMEOUT} seconds")
        except aiohttp.ClientError as e:
            raise Exception(f"Network error during download: {str(e)}")
        except Exception as e:
            logger.error(f"Download failed: {str(e)}")
            raise

    @staticmethod
    def _is_valid_content_type(content_type: str) -> bool:
        """Check if content type is allowed"""
        # Extract base content type (ignore charset, etc.)
        base_type = content_type.split(';')[0].strip().lower()
        return base_type in Config.ALLOWED_MIME_TYPES

    @staticmethod
    def _get_extension_from_content_type(content_type: str) -> str:
        """Get file extension from content type"""
        base_type = content_type.split(';')[0].strip().lower()

        extension_map = {
            'image/jpeg': '.jpg',
            'image/jpg': '.jpg',
            'image/png': '.png',
            'video/mp4': '.mp4',
            'video/quicktime': '.mov',
            'video/x-msvideo': '.avi',
            'audio/mpeg': '.mp3'
        }

        return extension_map.get(base_type, '.tmp')

    @staticmethod
    def cleanup_file(file_path: str) -> None:
        """Delete a temporary file"""
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
                logger.info(f"Cleaned up temporary file: {file_path}")
        except Exception as e:
            logger.warning(f"Failed to cleanup file {file_path}: {str(e)}")

    @staticmethod
    def validate_file_extension(file_path: str) -> bool:
        """Validate file has allowed extension"""
        ext = Path(file_path).suffix.lower()
        return ext in Config.ALLOWED_EXTENSIONS
