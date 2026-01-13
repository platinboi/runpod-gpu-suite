"""
Simple API Key Authentication Service
Stores API keys in JSON file for now, easy to migrate to PostgreSQL later
"""

import json
import hashlib
import secrets
import logging
import os
from pathlib import Path
from typing import Optional, Dict, List
from datetime import datetime, timezone
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class APIKey(BaseModel):
    """API Key model"""
    id: str
    user_id: str
    key_hash: str
    key_prefix: str  # First 16 chars for display (e.g., sk_live_abc123...)
    name: str
    is_active: bool = True
    created_at: str
    last_used_at: Optional[str] = None

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class User(BaseModel):
    """User model"""
    id: str
    email: str
    name: str
    plan_tier: str = "default"  # default, pro, enterprise
    created_at: str

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class AuthService:
    """Handles API key authentication and user management"""

    def __init__(self, data_file: str = "./data/api_keys.json"):
        self.data_file = Path(data_file)
        self.data_file.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_data_file()

    def _ensure_data_file(self):
        """Create data file if it doesn't exist"""
        if not self.data_file.exists():
            initial_data = {
                "users": [],
                "api_keys": []
            }
            self.data_file.write_text(json.dumps(initial_data, indent=2))
            logger.info(f"Created auth data file: {self.data_file}")

    def _load_data(self) -> Dict:
        """Load data from JSON file"""
        try:
            return json.loads(self.data_file.read_text())
        except Exception as e:
            logger.error(f"Failed to load auth data: {e}")
            return {"users": [], "api_keys": []}

    def _save_data(self, data: Dict):
        """Save data to JSON file"""
        try:
            self.data_file.write_text(json.dumps(data, indent=2))
        except Exception as e:
            logger.error(f"Failed to save auth data: {e}")

    def generate_api_key(self, user_id: str, name: str = "API Key") -> tuple[str, APIKey]:
        """
        Generate a new API key for a user

        Returns:
            tuple: (plaintext_key, api_key_record)
            The plaintext key should be shown ONCE to the user and never stored
        """
        # Generate cryptographically secure key
        key = f"sk_live_{secrets.token_urlsafe(32)}"
        key_hash = hashlib.sha256(key.encode()).hexdigest()
        key_prefix = key[:16]  # sk_live_abc123...

        # Create API key record
        api_key = APIKey(
            id=secrets.token_urlsafe(16),
            user_id=user_id,
            key_hash=key_hash,
            key_prefix=key_prefix,
            name=name,
            is_active=True,
            created_at=datetime.now(timezone.utc).isoformat(),
            last_used_at=None
        )

        # Save to file
        data = self._load_data()
        data["api_keys"].append(api_key.dict())
        self._save_data(data)

        logger.info(f"Generated API key for user {user_id}: {key_prefix}...")

        return key, api_key

    def validate_api_key(self, provided_key: str) -> Optional[User]:
        """
        Validate an API key and return the associated user

        Args:
            provided_key: The API key provided in the request

        Returns:
            User object if valid, None if invalid
        """
        if not provided_key:
            return None

        persistent = os.getenv("PERSISTENT_API_KEY")
        if persistent and provided_key == persistent:
            return User(
                id="persistent",
                email="persistent@local",
                name="Persistent API Key",
                plan_tier="default",
                created_at=datetime.now(timezone.utc).isoformat()
            )

        # Hash the provided key
        key_hash = hashlib.sha256(provided_key.encode()).hexdigest()

        # Load data
        data = self._load_data()

        # Find matching API key
        api_key = None
        for key_data in data["api_keys"]:
            if key_data["key_hash"] == key_hash and key_data["is_active"]:
                api_key = APIKey(**key_data)
                break

        if not api_key:
            logger.warning(f"Invalid API key attempt")
            return None

        # Update last_used_at
        for key_data in data["api_keys"]:
            if key_data["id"] == api_key.id:
                key_data["last_used_at"] = datetime.now(timezone.utc).isoformat()
                break
        self._save_data(data)

        # Get user
        user = self.get_user(api_key.user_id)
        if not user:
            logger.error(f"API key {api_key.id} references non-existent user {api_key.user_id}")
            return None

        return user

    def create_user(
        self,
        email: str,
        name: str,
        plan_tier: str = "default",
        user_id: Optional[str] = None
    ) -> User:
        """Create a new user"""
        user = User(
            id=user_id or secrets.token_urlsafe(16),
            email=email,
            name=name,
            plan_tier=plan_tier,
            created_at=datetime.now(timezone.utc).isoformat()
        )

        data = self._load_data()
        data["users"].append(user.dict())
        self._save_data(data)

        logger.info(f"Created user: {user.id} ({email})")

        return user

    def get_user(self, user_id: str) -> Optional[User]:
        """Get a user by ID"""
        data = self._load_data()
        for user_data in data["users"]:
            if user_data["id"] == user_id:
                return User(**user_data)
        return None

    def list_user_api_keys(self, user_id: str) -> List[APIKey]:
        """List all API keys for a user"""
        data = self._load_data()
        keys = []
        for key_data in data["api_keys"]:
            if key_data["user_id"] == user_id:
                keys.append(APIKey(**key_data))
        return keys

    def revoke_api_key(self, key_id: str) -> bool:
        """Revoke an API key"""
        data = self._load_data()
        for key_data in data["api_keys"]:
            if key_data["id"] == key_id:
                key_data["is_active"] = False
                self._save_data(data)
                logger.info(f"Revoked API key: {key_id}")
                return True
        return False

    def bootstrap_default_user(self) -> tuple[User, str]:
        """
        Create a default user and API key for initial setup
        Only creates if no users exist

        Checks for PERSISTENT_API_KEY environment variable to use a persistent key
        across redeployments instead of generating a new one each time.

        Returns:
            tuple: (user, api_key) or (None, None) if users already exist
        """
        data = self._load_data()

        # Check if any users exist
        if data["users"]:
            logger.info("Users already exist, skipping bootstrap")
            return None, None

        # Check for persistent API key from environment variable
        persistent_key = os.getenv("PERSISTENT_API_KEY")

        # Create default user
        user = self.create_user(
            email="admin@localhost",
            name="Default User",
            plan_tier="default",
            user_id="default"
        )

        # Reload data to include the newly created user
        data = self._load_data()

        # Use persistent key if provided, otherwise generate new one
        if persistent_key:
            # Validate key format (should start with sk_live_)
            if not persistent_key.startswith("sk_live_"):
                logger.warning("PERSISTENT_API_KEY doesn't start with 'sk_live_', generating new key instead")
                api_key, _ = self.generate_api_key(user_id=user.id, name="Default API Key")
            else:
                # Use the persistent key from environment
                key_hash = hashlib.sha256(persistent_key.encode()).hexdigest()
                key_prefix = persistent_key[:16]

                api_key_obj = APIKey(
                    id=f"key_{secrets.token_hex(8)}",
                    user_id=user.id,
                    key_hash=key_hash,
                    key_prefix=key_prefix,
                    name="Persistent API Key",
                    is_active=True,
                    created_at=datetime.now(timezone.utc).isoformat()
                )

                # Save to data file (data now includes the user)
                data["api_keys"].append(api_key_obj.dict())
                self._save_data(data)

                api_key = persistent_key
                logger.info("✓ Using PERSISTENT_API_KEY from environment variable")
        else:
            # Generate new random API key
            api_key, _ = self.generate_api_key(user_id=user.id, name="Default API Key")

        logger.info(f"✓ Bootstrap complete!")
        logger.info(f"✓ User ID: {user.id}")
        logger.info(f"✓ API Key: {api_key}")
        logger.info(f"✓ Save this API key - it won't be shown again!")

        return user, api_key
