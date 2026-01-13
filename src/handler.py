"""
RunPod Serverless Handler for GPU-accelerated media processing.

Supports all endpoints from the original FFmpeg scripts:
- /outfit - 9-image outfit collage
- /outfit-single - 6-image overlapping collage
- /pov - 8-image POV collage
- /merge - Merge clips with overlays
- /overlay - Text overlay
- /rembg - Background removal (GPU)
- /templates - Template CRUD operations
- /health - Health check
"""
import os
import sys
import uuid
import time
import logging
import asyncio

# Add src directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import runpod
from config import Config, list_templates

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Ensure temp directory exists
os.makedirs(Config.TEMP_DIR, exist_ok=True)

# Initialize services (lazy loading to reduce cold start)
_services = {}

def get_service(name: str):
    """Lazy load services to minimize cold start time."""
    if name not in _services:
        if name == 'outfit':
            from services.outfit_service import OutfitService
            _services[name] = OutfitService()
        elif name == 'outfit_single':
            from services.outfit_single_service import OutfitSingleService
            _services[name] = OutfitSingleService()
        elif name == 'pov':
            from services.pov_service import POVTemplateService
            _services[name] = POVTemplateService()
        elif name == 'merge':
            from services.merge_service import MergeService
            _services[name] = MergeService()
        elif name == 'ffmpeg':
            from services.ffmpeg_service import FFmpegService
            _services[name] = FFmpegService()
        elif name == 'rembg':
            from services.rembg_service import RembgService
            _services[name] = RembgService()
        elif name == 'storage':
            from services.storage_service import StorageService
            _services[name] = StorageService()
        elif name == 'download':
            from services.download_service import DownloadService
            _services[name] = DownloadService()
        elif name == 'template':
            from services.template_service import TemplateService
            _services[name] = TemplateService()
        elif name == 'database':
            from services.database_service import DatabaseService
            _services[name] = DatabaseService()
    return _services[name]


def cleanup_file(path: str):
    """Safely remove a temporary file."""
    if path and os.path.exists(path):
        try:
            os.remove(path)
            logger.info(f"Cleaned up: {path}")
        except Exception as e:
            logger.warning(f"Failed to cleanup {path}: {e}")


# ============================================================================
# OUTFIT COLLAGE (9 images)
# ============================================================================
async def handle_outfit(input_data: dict) -> dict:
    """Create 9-image outfit collage video."""
    from models.schemas import OutfitRequest

    start_time = time.time()
    output_path = None

    try:
        # Parse request
        request = OutfitRequest(**input_data)

        output_filename = f"outfit_{uuid.uuid4()}.mp4"
        output_path = os.path.join(Config.TEMP_DIR, output_filename)

        # Process outfit video
        outfit_service = get_service('outfit')
        result = await outfit_service.create_outfit_video(
            request=request,
            output_path=output_path
        )

        processing_time = time.time() - start_time

        # Upload to R2
        storage_service = get_service('storage')
        if storage_service.enabled:
            r2_url = await storage_service.upload_file(
                file_path=output_path,
                object_name=f"outfits/{output_filename}",
                user_id=None,
                file_type="outputs",
                public=True
            )

            cleanup_file(output_path)

            return {
                "status": "success",
                "message": "Outfit video created successfully",
                "filename": output_filename,
                "download_url": r2_url,
                "processing_time": processing_time
            }
        else:
            return {"error": "R2 storage not enabled"}

    except Exception as e:
        logger.error(f"Error in outfit: {e}")
        cleanup_file(output_path)
        return {"error": str(e)}


# ============================================================================
# OUTFIT SINGLE COLLAGE (6 images, overlapping)
# ============================================================================
async def handle_outfit_single(input_data: dict) -> dict:
    """Create 6-image overlapping outfit collage video."""
    from models.schemas import OutfitSingleRequest

    start_time = time.time()
    output_path = None

    try:
        request = OutfitSingleRequest(**input_data)

        output_filename = f"outfit_single_{uuid.uuid4()}.mp4"
        output_path = os.path.join(Config.TEMP_DIR, output_filename)

        outfit_single_service = get_service('outfit_single')
        result = await outfit_single_service.create_outfit_single_video(
            request=request,
            output_path=output_path
        )

        processing_time = time.time() - start_time

        storage_service = get_service('storage')
        if storage_service.enabled:
            r2_url = await storage_service.upload_file(
                file_path=output_path,
                object_name=f"outfit-single/{output_filename}",
                user_id=None,
                file_type="outputs",
                public=True
            )

            cleanup_file(output_path)

            return {
                "status": "success",
                "message": "Outfit-single video created successfully",
                "filename": output_filename,
                "download_url": r2_url,
                "processing_time": processing_time
            }
        else:
            return {"error": "R2 storage not enabled"}

    except Exception as e:
        logger.error(f"Error in outfit-single: {e}")
        cleanup_file(output_path)
        return {"error": str(e)}


# ============================================================================
# POV COLLAGE (8 images)
# ============================================================================
async def handle_pov(input_data: dict) -> dict:
    """Create 8-image POV collage video."""
    from models.schemas import POVTemplateRequest

    start_time = time.time()
    output_path = None

    try:
        request = POVTemplateRequest(**input_data)

        output_filename = f"pov_{uuid.uuid4()}.mp4"
        output_path = os.path.join(Config.TEMP_DIR, output_filename)

        pov_service = get_service('pov')
        result = await pov_service.create_pov_video(
            request=request,
            output_path=output_path
        )

        processing_time = time.time() - start_time

        storage_service = get_service('storage')
        if storage_service.enabled:
            r2_url = await storage_service.upload_file(
                file_path=output_path,
                object_name=f"pov/{output_filename}",
                user_id=None,
                file_type="outputs",
                public=True
            )

            cleanup_file(output_path)

            return {
                "status": "success",
                "message": "POV video created successfully",
                "filename": output_filename,
                "download_url": r2_url,
                "processing_time": processing_time
            }
        else:
            return {"error": "R2 storage not enabled"}

    except Exception as e:
        logger.error(f"Error in pov: {e}")
        cleanup_file(output_path)
        return {"error": str(e)}


# ============================================================================
# MERGE CLIPS
# ============================================================================
async def handle_merge(input_data: dict) -> dict:
    """Merge multiple video clips with overlays."""
    start_time = time.time()
    output_path = None

    try:
        clips = input_data.get('clips', [])
        output_format = input_data.get('output_format', 'mp4')
        first_clip_duration = input_data.get('first_clip_duration')
        first_clip_trim_mode = input_data.get('first_clip_trim_mode', 'both')

        output_filename = f"merged_{uuid.uuid4()}.{output_format}"
        output_path = os.path.join(Config.TEMP_DIR, output_filename)

        # Convert clips to config format
        clip_configs = [
            {
                'url': clip.get('url'),
                'text': clip.get('text'),
                'template': clip.get('template', 'default'),
                'overrides': clip.get('overrides')
            }
            for clip in clips
        ]

        merge_service = get_service('merge')
        result = await merge_service.process_merge_request(
            clip_configs=clip_configs,
            output_path=output_path,
            first_clip_duration=first_clip_duration,
            first_clip_trim_mode=first_clip_trim_mode
        )

        processing_time = time.time() - start_time

        storage_service = get_service('storage')
        if storage_service.enabled:
            r2_url = await storage_service.upload_file(
                file_path=output_path,
                object_name=f"merged/{output_filename}",
                user_id=None,
                file_type="outputs",
                public=True
            )

            cleanup_file(output_path)

            return {
                "status": "success",
                "message": f"Successfully merged {len(clips)} clips",
                "filename": output_filename,
                "download_url": r2_url,
                "clips_processed": len(clips),
                "processing_time": processing_time,
                "total_duration": result.get('duration')
            }
        else:
            return {"error": "R2 storage not enabled"}

    except Exception as e:
        logger.error(f"Error in merge: {e}")
        cleanup_file(output_path)
        return {"error": str(e)}


# ============================================================================
# TEXT OVERLAY
# ============================================================================
async def handle_overlay(input_data: dict) -> dict:
    """Add text overlay to image/video from URL."""
    from models.schemas import TextOverrideOptions
    from pathlib import Path

    start_time = time.time()
    input_path = None
    output_path = None

    try:
        url = input_data.get('url')
        text = input_data.get('text', '')
        template = input_data.get('template', 'default')
        overrides = input_data.get('overrides')
        output_format = input_data.get('output_format', 'same')

        # Download file
        download_service = get_service('download')
        input_path, content_type = await download_service.download_from_url(url)

        # Validate
        if not download_service.validate_file_extension(input_path):
            raise ValueError("Invalid file type")

        # Determine output extension
        output_ext = Path(input_path).suffix
        if output_format != "same":
            output_ext = f".{output_format}"

        output_filename = f"{uuid.uuid4()}{output_ext}"
        output_path = os.path.join(Config.TEMP_DIR, output_filename)

        # Parse overrides
        override_options = None
        if overrides:
            override_options = TextOverrideOptions(**overrides)

        # Process with FFmpeg
        ffmpeg_service = get_service('ffmpeg')
        result = ffmpeg_service.add_text_overlay(
            input_path=input_path,
            output_path=output_path,
            text=text,
            template_name=template,
            overrides=override_options
        )

        processing_time = time.time() - start_time

        # Upload to R2
        storage_service = get_service('storage')
        if storage_service.enabled:
            r2_url = await storage_service.upload_file(
                file_path=output_path,
                object_name=f"overlays/{output_filename}",
                user_id=None,
                file_type="outputs",
                public=True
            )

            cleanup_file(input_path)
            cleanup_file(output_path)

            return {
                "status": "success",
                "message": "Overlay applied successfully",
                "filename": output_filename,
                "download_url": r2_url,
                "processing_time": processing_time
            }
        else:
            cleanup_file(input_path)
            return {"error": "R2 storage not enabled"}

    except Exception as e:
        logger.error(f"Error in overlay: {e}")
        cleanup_file(input_path)
        cleanup_file(output_path)
        return {"error": str(e)}


# ============================================================================
# BACKGROUND REMOVAL (GPU)
# ============================================================================
async def handle_rembg(input_data: dict) -> dict:
    """Remove background from image using GPU-accelerated rembg."""
    start_time = time.time()
    input_path = None
    output_path = None

    try:
        image_url = input_data.get('image_url')
        model = input_data.get('model', 'birefnet-general')
        alpha_matting = input_data.get('alpha_matting', False)
        foreground_threshold = input_data.get('foreground_threshold', 240)
        background_threshold = input_data.get('background_threshold', 15)
        erode_size = input_data.get('erode_size', 8)
        post_process_mask = input_data.get('post_process_mask', True)
        bgcolor = input_data.get('bgcolor')
        folder = input_data.get('folder', 'rembg')

        # Download image
        download_service = get_service('download')
        input_path, _ = await download_service.download_from_url(image_url)

        if not download_service.validate_file_extension(input_path):
            raise ValueError("Invalid file type (images only)")

        output_filename = f"rembg_{uuid.uuid4()}.png"
        output_path = os.path.join(Config.TEMP_DIR, output_filename)

        # Process with rembg (GPU accelerated)
        rembg_service = get_service('rembg')

        # Run in thread pool to avoid blocking
        await asyncio.to_thread(
            rembg_service.remove_background,
            input_path=input_path,
            output_path=output_path,
            model=model,
            alpha_matting=alpha_matting,
            foreground_threshold=foreground_threshold,
            background_threshold=background_threshold,
            erode_size=erode_size,
            post_process_mask=post_process_mask,
            bgcolor=bgcolor
        )

        processing_time = time.time() - start_time

        # Upload to R2
        storage_service = get_service('storage')
        if storage_service.enabled:
            r2_url = await storage_service.upload_file(
                file_path=output_path,
                object_name=f"{folder}/{output_filename}",
                user_id=None,
                file_type="outputs",
                public=True
            )

            cleanup_file(input_path)
            cleanup_file(output_path)

            return {
                "status": "success",
                "message": "Background removed successfully",
                "filename": output_filename,
                "download_url": r2_url,
                "processing_time": processing_time,
                "model": model
            }
        else:
            cleanup_file(input_path)
            return {"error": "R2 storage not enabled"}

    except Exception as e:
        logger.error(f"Error in rembg: {e}")
        cleanup_file(input_path)
        cleanup_file(output_path)
        return {"error": str(e)}


# ============================================================================
# TEMPLATE OPERATIONS
# ============================================================================
def handle_templates_list() -> dict:
    """List all available templates."""
    try:
        templates = list_templates()
        return {
            "status": "success",
            "templates": templates,
            "count": len(templates)
        }
    except Exception as e:
        logger.error(f"Error listing templates: {e}")
        return {"error": str(e)}


def handle_template_get(input_data: dict) -> dict:
    """Get a specific template by name."""
    try:
        name = input_data.get('name')
        template_service = get_service('template')
        template = template_service.get_template(name)

        if not template:
            return {"error": f"Template '{name}' not found"}

        template['created_at'] = str(template['created_at'])
        template['updated_at'] = str(template['updated_at'])

        return {"status": "success", "template": template}
    except Exception as e:
        logger.error(f"Error getting template: {e}")
        return {"error": str(e)}


def handle_template_create(input_data: dict) -> dict:
    """Create a new template."""
    try:
        template_data = input_data.copy()
        if 'font_path' not in template_data:
            template_data['font_path'] = Config.TIKTOK_SANS_SEMIBOLD

        template_service = get_service('template')
        created = template_service.create_template(template_data)

        created['created_at'] = str(created['created_at'])
        created['updated_at'] = str(created['updated_at'])

        return {"status": "success", "template": created}
    except ValueError as e:
        return {"error": str(e)}
    except Exception as e:
        logger.error(f"Error creating template: {e}")
        return {"error": str(e)}


def handle_template_update(input_data: dict) -> dict:
    """Update an existing template."""
    try:
        name = input_data.pop('name')
        template_data = input_data.copy()

        if 'font_path' not in template_data:
            template_data['font_path'] = Config.TIKTOK_SANS_SEMIBOLD

        template_service = get_service('template')
        updated = template_service.update_template(name, template_data)

        if not updated:
            return {"error": f"Template '{name}' not found"}

        updated['created_at'] = str(updated['created_at'])
        updated['updated_at'] = str(updated['updated_at'])

        return {"status": "success", "template": updated}
    except ValueError as e:
        return {"error": str(e)}
    except Exception as e:
        logger.error(f"Error updating template: {e}")
        return {"error": str(e)}


def handle_template_delete(input_data: dict) -> dict:
    """Delete a template."""
    try:
        name = input_data.get('name')
        template_service = get_service('template')
        deleted = template_service.delete_template(name)

        if not deleted:
            return {"error": f"Template '{name}' not found"}

        return {"status": "success", "message": f"Template '{name}' deleted"}
    except ValueError as e:
        return {"error": str(e)}
    except Exception as e:
        logger.error(f"Error deleting template: {e}")
        return {"error": str(e)}


def handle_template_duplicate(input_data: dict) -> dict:
    """Duplicate an existing template."""
    try:
        name = input_data.get('name')
        new_name = input_data.get('new_name')

        template_service = get_service('template')
        duplicated = template_service.duplicate_template(name, new_name)

        duplicated['created_at'] = str(duplicated['created_at'])
        duplicated['updated_at'] = str(duplicated['updated_at'])

        return {"status": "success", "template": duplicated}
    except ValueError as e:
        return {"error": str(e)}
    except Exception as e:
        logger.error(f"Error duplicating template: {e}")
        return {"error": str(e)}


# ============================================================================
# HEALTH CHECK
# ============================================================================
def handle_health() -> dict:
    """Health check endpoint."""
    try:
        ffmpeg_service = get_service('ffmpeg')
        ffmpeg_available = ffmpeg_service.check_ffmpeg_available()
        fonts_available = (
            ffmpeg_service.check_font_available(Config.TIKTOK_SANS_MEDIUM) and
            ffmpeg_service.check_font_available(Config.TIKTOK_SANS_SEMIBOLD)
        )

        # Check database (optional)
        database_available = None
        try:
            db_service = get_service('database')
            database_available = db_service.check_connection()
        except Exception as e:
            logger.warning(f"Database health check failed: {e}")
            database_available = False

        # Check if GPU is available
        gpu_available = False
        try:
            import torch
            gpu_available = torch.cuda.is_available()
        except ImportError:
            pass

        is_healthy = ffmpeg_available and fonts_available

        return {
            "status": "healthy" if is_healthy else "unhealthy",
            "ffmpeg_available": ffmpeg_available,
            "fonts_available": fonts_available,
            "database_available": database_available,
            "gpu_available": gpu_available,
            "version": "1.0.0"
        }
    except Exception as e:
        logger.error(f"Health check error: {e}")
        return {"status": "unhealthy", "error": str(e)}


# ============================================================================
# MAIN HANDLER
# ============================================================================
async def async_handler(job: dict) -> dict:
    """
    RunPod serverless async handler.

    Routes requests to appropriate service based on 'action' field.

    Supported actions:
    - outfit: 9-image outfit collage
    - outfit-single: 6-image overlapping collage
    - pov: 8-image POV collage
    - merge: Merge video clips with overlays
    - overlay: Add text overlay to image/video
    - rembg: Remove background from image (GPU)
    - templates: List all templates
    - template_get: Get template by name
    - template_create: Create new template
    - template_update: Update template
    - template_delete: Delete template
    - template_duplicate: Duplicate template
    - health: Health check
    """
    job_input = job.get("input", {})
    action = job_input.get("action", "")

    logger.info(f"Received action: {action}")

    try:
        # Collages (daily use - highest priority)
        if action == "outfit":
            return await handle_outfit(job_input)
        elif action == "outfit-single":
            return await handle_outfit_single(job_input)
        elif action == "pov":
            return await handle_pov(job_input)

        # Video processing
        elif action == "merge":
            return await handle_merge(job_input)
        elif action == "overlay":
            return await handle_overlay(job_input)

        # Background removal (GPU accelerated)
        elif action == "rembg":
            return await handle_rembg(job_input)

        # Template operations
        elif action == "templates":
            return handle_templates_list()
        elif action == "template_get":
            return handle_template_get(job_input)
        elif action == "template_create":
            return handle_template_create(job_input)
        elif action == "template_update":
            return handle_template_update(job_input)
        elif action == "template_delete":
            return handle_template_delete(job_input)
        elif action == "template_duplicate":
            return handle_template_duplicate(job_input)

        # Health check
        elif action == "health":
            return handle_health()

        else:
            return {"error": f"Unknown action: {action}"}

    except Exception as e:
        logger.error(f"Handler error: {e}", exc_info=True)
        return {"error": str(e)}


# Start RunPod serverless with async handler
runpod.serverless.start({"handler": async_handler})
