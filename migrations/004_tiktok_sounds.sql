-- Migration 004: TikTok sounds table for storing audio tracks
-- Used by stein, outfit, and outfit-single endpoints

CREATE TABLE IF NOT EXISTS tiktok_sounds (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    url TEXT NOT NULL,
    duration_seconds NUMERIC(10,2),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Index for random selection and name lookups
CREATE INDEX IF NOT EXISTS idx_tiktok_sounds_name ON tiktok_sounds(name);
