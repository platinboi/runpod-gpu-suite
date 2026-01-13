"""
Usage Tracking Service
Tracks API usage for billing and analytics
"""

import json
import logging
from pathlib import Path
from typing import Optional, List, Dict
from datetime import datetime, timezone
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class UsageRecord(BaseModel):
    """Usage record for a single API call"""
    id: str
    user_id: str
    endpoint: str  # /overlay/url or /overlay/upload
    input_file_size_bytes: int
    output_file_size_bytes: int
    processing_time_ms: int
    template_used: str
    has_custom_overrides: bool
    timestamp: str

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class UsageService:
    """Handles usage tracking and reporting"""

    def __init__(self, data_file: str = "./data/usage_records.json"):
        self.data_file = Path(data_file)
        self.data_file.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_data_file()

    def _ensure_data_file(self):
        """Create data file if it doesn't exist"""
        if not self.data_file.exists():
            initial_data = {
                "records": []
            }
            self.data_file.write_text(json.dumps(initial_data, indent=2))
            logger.info(f"Created usage data file: {self.data_file}")

    def _load_data(self) -> Dict:
        """Load data from JSON file"""
        try:
            return json.loads(self.data_file.read_text())
        except Exception as e:
            logger.error(f"Failed to load usage data: {e}")
            return {"records": []}

    def _save_data(self, data: Dict):
        """Save data to JSON file"""
        try:
            # For performance, only keep last 10000 records in JSON
            # In production, this would go to PostgreSQL
            if len(data["records"]) > 10000:
                data["records"] = data["records"][-10000:]

            self.data_file.write_text(json.dumps(data, indent=2))
        except Exception as e:
            logger.error(f"Failed to save usage data: {e}")

    def track_usage(
        self,
        user_id: str,
        endpoint: str,
        input_file_size_bytes: int,
        output_file_size_bytes: int,
        processing_time_ms: int,
        template_used: str,
        has_custom_overrides: bool = False,
        record_id: Optional[str] = None
    ) -> UsageRecord:
        """Track a usage event"""
        import secrets

        record = UsageRecord(
            id=record_id or secrets.token_urlsafe(16),
            user_id=user_id,
            endpoint=endpoint,
            input_file_size_bytes=input_file_size_bytes,
            output_file_size_bytes=output_file_size_bytes,
            processing_time_ms=processing_time_ms,
            template_used=template_used,
            has_custom_overrides=has_custom_overrides,
            timestamp=datetime.now(timezone.utc).isoformat()
        )

        # Save to file
        data = self._load_data()
        data["records"].append(record.dict())
        self._save_data(data)

        logger.info(
            f"Tracked usage for user {user_id}: "
            f"{endpoint}, {processing_time_ms}ms, "
            f"{output_file_size_bytes} bytes"
        )

        return record

    def get_user_usage(
        self,
        user_id: str,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> List[UsageRecord]:
        """Get usage records for a user within a date range"""
        data = self._load_data()
        records = []

        for record_data in data["records"]:
            if record_data["user_id"] != user_id:
                continue

            record = UsageRecord(**record_data)
            record_time = datetime.fromisoformat(record.timestamp)

            if start_date and record_time < start_date:
                continue
            if end_date and record_time > end_date:
                continue

            records.append(record)

        return records

    def get_usage_summary(
        self,
        user_id: str,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> Dict:
        """Get aggregated usage summary for a user"""
        records = self.get_user_usage(user_id, start_date, end_date)

        if not records:
            return {
                "user_id": user_id,
                "total_requests": 0,
                "total_input_bytes": 0,
                "total_output_bytes": 0,
                "total_processing_time_ms": 0,
                "avg_processing_time_ms": 0,
                "start_date": start_date.isoformat() if start_date else None,
                "end_date": end_date.isoformat() if end_date else None
            }

        total_input_bytes = sum(r.input_file_size_bytes for r in records)
        total_output_bytes = sum(r.output_file_size_bytes for r in records)
        total_processing_time_ms = sum(r.processing_time_ms for r in records)

        return {
            "user_id": user_id,
            "total_requests": len(records),
            "total_input_bytes": total_input_bytes,
            "total_output_bytes": total_output_bytes,
            "total_processing_time_ms": total_processing_time_ms,
            "avg_processing_time_ms": total_processing_time_ms // len(records),
            "total_input_mb": round(total_input_bytes / (1024 * 1024), 2),
            "total_output_mb": round(total_output_bytes / (1024 * 1024), 2),
            "total_processing_seconds": round(total_processing_time_ms / 1000, 2),
            "start_date": start_date.isoformat() if start_date else records[0].timestamp,
            "end_date": end_date.isoformat() if end_date else records[-1].timestamp
        }

    def get_monthly_summary(self, user_id: str, year: int, month: int) -> Dict:
        """Get usage summary for a specific month"""
        from datetime import date
        from calendar import monthrange

        # Get first and last day of month
        last_day = monthrange(year, month)[1]
        start_date = datetime(year, month, 1, 0, 0, 0, tzinfo=timezone.utc)
        end_date = datetime(year, month, last_day, 23, 59, 59, tzinfo=timezone.utc)

        return self.get_usage_summary(user_id, start_date, end_date)
