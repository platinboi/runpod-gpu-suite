"""
Storage service for handling R2 uploads (future-ready, currently disabled)
"""
import os
import logging
from typing import Optional
from config import Config

logger = logging.getLogger(__name__)


class StorageService:
    """
    Handles file storage to Cloudflare R2
    Currently disabled by default - enable via R2_ENABLED env variable
    """

    def __init__(self):
        self.enabled = Config.R2_ENABLED

        if self.enabled:
            try:
                import boto3
                from botocore.config import Config as BotoConfig

                # Initialize R2 client using S3-compatible API
                self.client = boto3.client(
                    's3',
                    endpoint_url=Config.R2_ENDPOINT,
                    aws_access_key_id=Config.R2_ACCESS_KEY_ID,
                    aws_secret_access_key=Config.R2_SECRET_ACCESS_KEY,
                    config=BotoConfig(
                        signature_version='s3v4',
                        region_name='auto'
                    )
                )
                self.bucket_name = Config.R2_BUCKET_NAME
                self.custom_domain = Config.R2_CUSTOM_DOMAIN
                logger.info("R2 storage service initialized successfully")
            except ImportError:
                logger.warning("boto3 not installed - R2 storage disabled")
                self.enabled = False
            except Exception as e:
                logger.error(f"Failed to initialize R2 client: {str(e)}")
                self.enabled = False
        else:
            logger.info("R2 storage service is disabled")

    def get_user_path(self, user_id: str, file_type: str, filename: str) -> str:
        """
        Generate user-scoped path for multi-tenant storage

        Args:
            user_id: User ID for scoping
            file_type: 'inputs' or 'outputs'
            filename: Name of the file

        Returns:
            Scoped path like: users/{user_id}/outputs/2024-11/filename.mp4
        """
        from datetime import datetime
        month = datetime.now().strftime('%Y-%m')
        return f"users/{user_id}/{file_type}/{month}/{filename}"

    def get_simple_date_path(self, filename: str) -> str:
        """
        Generate human-readable timestamp path for public outputs in ffmpeg folder
        Format: ffmpeg/ffmpeg_HH-MM-SS_DD-MM-YYYY.ext
        Example: ffmpeg/ffmpeg_14-28-13_30-11-2025.mp4 (2:28:13 PM on Nov 30, 2025)

        Args:
            filename: Name of the file (extracts extension only)

        Returns:
            Path like: ffmpeg/ffmpeg_14-28-13_30-11-2025.mp4
        """
        from datetime import datetime
        import os

        # Extract extension only
        _, ext = os.path.splitext(filename)

        # Create human-readable timestamp: HH-MM-SS_DD-MM-YYYY
        now = datetime.now()
        time_part = f"{now.hour:02d}-{now.minute:02d}-{now.second:02d}"
        date_part = f"{now.day:02d}-{now.month:02d}-{now.year}"

        # Construct final path with underscore separator for readability
        new_filename = f"ffmpeg_{time_part}_{date_part}{ext}"
        return f"ffmpeg/{new_filename}"

    async def upload_file(
        self,
        file_path: str,
        object_name: Optional[str] = None,
        user_id: Optional[str] = None,
        file_type: str = "outputs",
        public: bool = False
    ) -> Optional[str]:
        """
        Upload a file to R2 bucket with optional user scoping

        Args:
            file_path: Local path to file
            object_name: S3 object name (if None, generates from file_path)
            user_id: User ID for multi-tenant scoping (if provided)
            file_type: 'inputs' or 'outputs' (used with user_id)
            public: If True, upload with public-read ACL and use simple date path

        Returns:
            Public URL of uploaded file, or None if upload failed
        """
        if not self.enabled:
            logger.debug("R2 upload skipped - service disabled")
            return None

        if object_name is None:
            filename = os.path.basename(file_path)
            if public:
                # Use simple date-based path for public URLs
                object_name = self.get_simple_date_path(filename)
            elif user_id:
                # Use user-scoped path for private files
                object_name = self.get_user_path(user_id, file_type, filename)
            else:
                object_name = filename

        try:
            # Upload file with appropriate ACL
            acl = 'public-read' if public else 'private'
            self.client.upload_file(
                file_path,
                self.bucket_name,
                object_name,
                ExtraArgs={'ACL': acl}
            )

            # Generate public URL using custom domain if configured
            if self.custom_domain:
                url = f"https://{self.custom_domain}/{object_name}"
            else:
                url = f"https://{self.bucket_name}.r2.dev/{object_name}"
            logger.info(f"Uploaded file to R2: {object_name} (public={public})")

            return url

        except Exception as e:
            logger.error(f"Failed to upload to R2: {str(e)}")
            return None

    async def delete_file(self, object_name: str) -> bool:
        """
        Delete a file from R2 bucket

        Args:
            object_name: S3 object name

        Returns:
            True if deleted successfully, False otherwise
        """
        if not self.enabled:
            return False

        try:
            self.client.delete_object(
                Bucket=self.bucket_name,
                Key=object_name
            )
            logger.info(f"Deleted file from R2: {object_name}")
            return True

        except Exception as e:
            logger.error(f"Failed to delete from R2: {str(e)}")
            return False

    def get_public_url(self, object_name: str) -> Optional[str]:
        """
        Get public URL for an object

        Args:
            object_name: S3 object name

        Returns:
            Public URL or None if service disabled
        """
        if not self.enabled:
            return None

        # Use custom domain if configured, otherwise use R2 dev domain
        if self.custom_domain:
            return f"https://{self.custom_domain}/{object_name}"
        else:
            return f"https://{self.bucket_name}.r2.dev/{object_name}"


# Example usage for future implementation:
"""
# In main.py or endpoint:

storage = StorageService()

# After processing file with FFmpeg:
if storage.enabled:
    # Upload processed file to R2
    r2_url = await storage.upload_file(output_path, f"processed/{filename}")

    # Return R2 URL instead of local file
    return {
        "status": "success",
        "url": r2_url
    }
else:
    # Return local file as download
    return FileResponse(output_path)
"""
