"""
Configuration and style templates for FFmpeg text overlay service
"""
import os
from typing import Dict, Any
from dataclasses import dataclass


# Environment configuration
class Config:
    """Application configuration"""
    MAX_FILE_SIZE = int(os.getenv("MAX_FILE_SIZE", 100 * 1024 * 1024))  # 100MB default
    UPLOAD_TIMEOUT = int(os.getenv("UPLOAD_TIMEOUT", 30))  # 30 seconds
    DOWNLOAD_TIMEOUT = int(os.getenv("DOWNLOAD_TIMEOUT", 300))  # 5 minutes for downloads
    TEMP_DIR = "/app/temp" if os.path.exists("/app") else "./temp"
    FONT_DIR = "/usr/share/fonts/truetype/custom" if os.path.exists("/usr/share/fonts/truetype/custom") else "./fonts"

    # Font paths
    TIKTOK_SANS_MEDIUM = os.path.join(FONT_DIR, "TikTokSans-Medium.ttf")
    TIKTOK_SANS_SEMIBOLD = os.path.join(FONT_DIR, "TikTokSans-SemiBold.ttf")

    # Aliases for compatibility (map to TikTok fonts)
    INTER_REGULAR = TIKTOK_SANS_MEDIUM
    INTER_BOLD = TIKTOK_SANS_SEMIBOLD

    # Allowed file formats
    ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".mp4", ".mov", ".avi", ".mp3"}
    ALLOWED_MIME_TYPES = {
        "image/jpeg", "image/png", "image/jpg",
        "video/mp4", "video/quicktime", "video/x-msvideo",
        "audio/mpeg",  # For TikTok sound MP3s
        "application/octet-stream"  # Fallback for uploads without proper MIME type
    }

    # R2 Configuration (optional - for future use)
    R2_ENABLED = os.getenv("R2_ENABLED", "false").lower() == "true"
    R2_ACCOUNT_ID = os.getenv("R2_ACCOUNT_ID", "")
    R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID", "")
    R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY", "")
    R2_BUCKET_NAME = os.getenv("R2_BUCKET_NAME", "")
    R2_CUSTOM_DOMAIN = os.getenv("R2_CUSTOM_DOMAIN", "")

    # Merge/Concat Configuration
    MAX_MERGE_CLIPS = int(os.getenv("MAX_MERGE_CLIPS", 10))  # Maximum clips per merge request
    MERGE_TIMEOUT = int(os.getenv("MERGE_TIMEOUT", 600))  # 10 minutes processing timeout


@dataclass
class TextStyle:
    """Text style configuration"""
    font_path: str
    font_size: int
    text_color: str
    border_width: int
    border_color: str
    shadow_x: int
    shadow_y: int
    shadow_color: str
    position: str
    background_enabled: bool
    background_color: str
    background_opacity: float
    text_opacity: float
    max_text_width_percent: int = 80
    line_spacing: int = -8  # Negative spacing for TikTok-style tight lines

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "font_path": self.font_path,
            "font_size": self.font_size,
            "text_color": self.text_color,
            "border_width": self.border_width,
            "border_color": self.border_color,
            "shadow_x": self.shadow_x,
            "shadow_y": self.shadow_y,
            "shadow_color": self.shadow_color,
            "position": self.position,
            "background_enabled": self.background_enabled,
            "background_color": self.background_color,
            "background_opacity": self.background_opacity,
            "text_opacity": self.text_opacity,
            "max_text_width_percent": self.max_text_width_percent,
            "line_spacing": self.line_spacing
        }


# Database configuration for PostgreSQL (Neon)
# Note: DATABASE_URL is managed by DatabaseService with its own defaults
# This is kept for reference/documentation purposes only
DATABASE_URL = os.getenv("DATABASE_URL", "")


def get_template(template_name: str) -> TextStyle:
    """
    Get a style template by name from database
    Falls back to default template if not found
    """
    from services.template_service import TemplateService

    try:
        template_service = TemplateService()
        template_data = template_service.get_template(template_name)

        if not template_data:
            # Fallback to default
            template_data = template_service.get_default_template()

        if template_data:
            # Convert DB record to TextStyle
            return TextStyle(
                font_path=template_data['font_path'],
                font_size=template_data['font_size'],
                text_color=template_data['text_color'],
                border_width=template_data['border_width'],
                border_color=template_data['border_color'],
                shadow_x=template_data['shadow_x'],
                shadow_y=template_data['shadow_y'],
                shadow_color=template_data['shadow_color'],
                position=template_data['position'],
                background_enabled=template_data['background_enabled'],
                background_color=template_data['background_color'],
                background_opacity=template_data['background_opacity'],
                text_opacity=template_data['text_opacity'],
                max_text_width_percent=template_data.get('max_text_width_percent', 80),
                line_spacing=template_data.get('line_spacing', -8)
            )
    except Exception as e:
        print(f"Error loading template from database: {e}")

    # Ultimate fallback - hardcoded default
    return TextStyle(
        font_path=Config.TIKTOK_SANS_SEMIBOLD,
        font_size=46,
        text_color="white",
        border_width=6,
        border_color="black",
        shadow_x=3,
        shadow_y=3,
        shadow_color="black",
        position="center",
        background_enabled=False,
        background_color="black",
        background_opacity=0.0,
        text_opacity=1.0,
        max_text_width_percent=80,
        line_spacing=-8
    )


def list_templates() -> Dict[str, Dict[str, Any]]:
    """List all available templates from database"""
    from services.template_service import TemplateService

    try:
        template_service = TemplateService()
        templates = template_service.list_templates()

        # Convert to expected format
        result = {}
        for template in templates:
            result[template['name']] = {
                'font_path': template['font_path'],
                'font_size': template['font_size'],
                'text_color': template['text_color'],
                'border_width': template['border_width'],
                'border_color': template['border_color'],
                'shadow_x': template['shadow_x'],
                'shadow_y': template['shadow_y'],
                'shadow_color': template['shadow_color'],
                'position': template['position'],
                'background_enabled': template['background_enabled'],
                'background_color': template['background_color'],
                'background_opacity': template['background_opacity'],
                'text_opacity': template['text_opacity'],
                'max_text_width_percent': template.get('max_text_width_percent', 80),
                'line_spacing': template.get('line_spacing', -8)
            }
        return result
    except Exception as e:
        print(f"Error listing templates from database: {e}")
        return {}
