"""
Template Service for managing text overlay templates
Provides CRUD operations for templates stored in PostgreSQL
"""

import logging
from typing import Optional, Dict, List
from datetime import datetime
from psycopg2.extras import RealDictCursor
from services.database_service import DatabaseService
from config import Config

logger = logging.getLogger(__name__)


class TemplateService:
    """Handles template CRUD operations"""

    def __init__(self):
        self.db = DatabaseService()

    def create_template(self, template_data: Dict) -> Dict:
        """
        Create a new template

        Args:
            template_data: Dictionary with template fields

        Returns:
            Created template as dictionary

        Raises:
            ValueError: If template name already exists
        """
        with self.db.get_connection() as conn:
            cursor = conn.cursor(cursor_factory=RealDictCursor)

            # Check if template exists
            cursor.execute("SELECT id FROM templates WHERE name = %s", (template_data['name'],))
            if cursor.fetchone():
                raise ValueError(f"Template '{template_data['name']}' already exists")

            # Insert template
            cursor.execute("""
                INSERT INTO templates (
                    name, font_path, font_size, font_weight, text_color,
                    border_width, border_color, shadow_x, shadow_y, shadow_color,
                    position, background_enabled, background_color,
                    background_opacity, text_opacity, alignment, max_text_width_percent, line_spacing
                ) VALUES (
                    %(name)s, %(font_path)s, %(font_size)s, %(font_weight)s, %(text_color)s,
                    %(border_width)s, %(border_color)s, %(shadow_x)s, %(shadow_y)s, %(shadow_color)s,
                    %(position)s, %(background_enabled)s, %(background_color)s,
                    %(background_opacity)s, %(text_opacity)s, %(alignment)s, %(max_text_width_percent)s, %(line_spacing)s
                )
                RETURNING *
            """, template_data)

            template = dict(cursor.fetchone())
            logger.info(f"Created template: {template['name']}")
            return template

    def get_template(self, name: str) -> Optional[Dict]:
        """
        Get a template by name

        Args:
            name: Template name

        Returns:
            Template as dictionary or None if not found
        """
        with self.db.get_connection() as conn:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute("SELECT * FROM templates WHERE name = %s", (name,))
            result = cursor.fetchone()
            return dict(result) if result else None

    def list_templates(self) -> List[Dict]:
        """
        Get all templates

        Returns:
            List of templates as dictionaries
        """
        with self.db.get_connection() as conn:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute("SELECT * FROM templates ORDER BY created_at DESC")
            return [dict(row) for row in cursor.fetchall()]

    def update_template(self, name: str, template_data: Dict) -> Optional[Dict]:
        """
        Update an existing template

        Args:
            name: Current template name
            template_data: Dictionary with updated fields

        Returns:
            Updated template as dictionary or None if not found
        """
        with self.db.get_connection() as conn:
            cursor = conn.cursor(cursor_factory=RealDictCursor)

            # Build SET clause dynamically from provided fields
            set_clauses = []
            values = []
            for key, value in template_data.items():
                if key != 'name':  # Name handled separately if provided
                    set_clauses.append(f"{key} = %s")
                    values.append(value)

            if not set_clauses:
                # No fields to update
                return self.get_template(name)

            # Add the WHERE clause value
            values.append(name)

            query = f"""
                UPDATE templates
                SET {', '.join(set_clauses)}
                WHERE name = %s
                RETURNING *
            """

            cursor.execute(query, values)
            result = cursor.fetchone()

            if result:
                logger.info(f"Updated template: {name}")
                return dict(result)
            return None

    def delete_template(self, name: str) -> bool:
        """
        Delete a template

        Args:
            name: Template name

        Returns:
            True if deleted, False if not found
        """
        with self.db.get_connection() as conn:
            cursor = conn.cursor()

            # Don't allow deleting default template
            cursor.execute("SELECT is_default FROM templates WHERE name = %s", (name,))
            result = cursor.fetchone()
            if result and result[0]:
                raise ValueError("Cannot delete default template")

            cursor.execute("DELETE FROM templates WHERE name = %s", (name,))
            deleted = cursor.rowcount > 0

            if deleted:
                logger.info(f"Deleted template: {name}")

            return deleted

    def duplicate_template(self, source_name: str, new_name: str) -> Dict:
        """
        Duplicate an existing template

        Args:
            source_name: Name of template to copy
            new_name: Name for the new template

        Returns:
            Created template as dictionary

        Raises:
            ValueError: If source doesn't exist or new name already exists
        """
        # Get source template
        source = self.get_template(source_name)
        if not source:
            raise ValueError(f"Template '{source_name}' not found")

        # Check if new name exists
        if self.get_template(new_name):
            raise ValueError(f"Template '{new_name}' already exists")

        # Create copy
        template_data = {k: v for k, v in source.items()
                        if k not in ['id', 'created_at', 'updated_at', 'is_default']}
        template_data['name'] = new_name

        return self.create_template(template_data)

    def template_exists(self, name: str) -> bool:
        """Check if a template exists"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM templates WHERE name = %s", (name,))
            return cursor.fetchone() is not None

    def get_default_template(self) -> Optional[Dict]:
        """Get the default template"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute("SELECT * FROM templates WHERE is_default = TRUE LIMIT 1")
            result = cursor.fetchone()
            if result:
                return dict(result)

            # Fallback to 'default' template by name
            cursor.execute("SELECT * FROM templates WHERE name = 'default' LIMIT 1")
            result = cursor.fetchone()
            return dict(result) if result else None

    def seed_default_template(self):
        """
        Seed the database with the default template if it doesn't exist
        Uses the hardcoded default from config.py
        """
        if self.template_exists('default'):
            logger.info("Default template already exists, skipping seed")
            return

        default_template = {
            'name': 'default',
            'font_path': Config.TIKTOK_SANS_SEMIBOLD,
            'font_size': 46,
            'font_weight': 500,
            'text_color': 'white',
            'border_width': 6,
            'border_color': 'black',
            'shadow_x': 3,
            'shadow_y': 3,
            'shadow_color': 'black',
            'position': 'center',
            'background_enabled': False,
            'background_color': 'black',
            'background_opacity': 0.0,
            'text_opacity': 1.0,
            'alignment': 'center',
            'max_text_width_percent': 80,
            'line_spacing': -8
        }

        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO templates (
                    name, font_path, font_size, font_weight, text_color,
                    border_width, border_color, shadow_x, shadow_y, shadow_color,
                    position, background_enabled, background_color,
                    background_opacity, text_opacity, alignment, max_text_width_percent, line_spacing,
                    is_default
                ) VALUES (
                    %(name)s, %(font_path)s, %(font_size)s, %(font_weight)s, %(text_color)s,
                    %(border_width)s, %(border_color)s, %(shadow_x)s, %(shadow_y)s, %(shadow_color)s,
                    %(position)s, %(background_enabled)s, %(background_color)s,
                    %(background_opacity)s, %(text_opacity)s, %(alignment)s, %(max_text_width_percent)s, %(line_spacing)s,
                    TRUE
                )
            """, default_template)

        logger.info("✓ Seeded default template")

    def update_default_template_font_path(self):
        """
        Force update the default template's font path to use absolute path.
        This ensures existing templates use the correct path in production.
        """
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE templates
                SET font_path = %s
                WHERE name = 'default'
            """, (Config.TIKTOK_SANS_SEMIBOLD,))
            conn.commit()
            logger.info(f"✓ Updated default template font path to: {Config.TIKTOK_SANS_SEMIBOLD}")

    def update_default_template_font_size(self, font_size: int = 46):
        """
        Force update the default template's font size.
        This ensures existing templates use the new font size.
        """
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE templates
                SET font_size = %s
                WHERE name = 'default'
            """, (font_size,))
            conn.commit()
            logger.info(f"✓ Updated default template font size to: {font_size}")

    def update_default_template_styling(self):
        """
        Update the default template's border and shadow settings to match TikTok-native styling.
        This ensures existing templates use the same visual style as the outfits endpoint.
        """
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE templates
                SET border_width = 6,
                    shadow_x = 3,
                    shadow_y = 3
                WHERE name = 'default'
            """)
            conn.commit()
            logger.info("✓ Updated default template styling (border: 6px, shadow: 3px offset)")
