-- Donna AI Database Schema v2
-- Run this in Nhost SQL editor (Hasura Console > Data > SQL)
-- This schema supports tasks, recurring tasks, accountability, and insights

-- ============================================
-- USERS TABLE (enhanced)
-- ============================================
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    phone VARCHAR(20) UNIQUE NOT NULL,
    name VARCHAR(255),
    timezone VARCHAR(50) DEFAULT 'Asia/Kolkata',
    preferences JSONB DEFAULT '{
        "morning_brief_time": "08:00",
        "evening_checkin_time": "18:00",
        "quiet_hours_start": "23:00",
        "quiet_hours_end": "07:00"
    }',
    learned_patterns JSONB DEFAULT '{}',  -- updated by weekly cron
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_users_phone ON users(phone);

-- ============================================
-- TASKS TABLE (one-time tasks)
-- ============================================
CREATE TABLE IF NOT EXISTS tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_phone VARCHAR(20) NOT NULL,
    title VARCHAR(500) NOT NULL,
    description TEXT,
    status VARCHAR(20) DEFAULT 'pending' CHECK (status IN ('pending', 'reminded', 'completed', 'dropped')),
    priority INT DEFAULT 3 CHECK (priority BETWEEN 1 AND 5),  -- 1=highest, 5=lowest

    -- Timing
    created_at TIMESTAMPTZ DEFAULT NOW(),
    remind_at TIMESTAMPTZ,  -- when to first remind
    due_date TIMESTAMPTZ,   -- optional hard deadline
    completed_at TIMESTAMPTZ,

    -- Vector reference for semantic search
    vector_id VARCHAR(255),  -- Pinecone ID

    -- Accountability tracking
    accountability JSONB DEFAULT '{
        "reminder_count": 0,
        "snooze_count": 0,
        "escalation_stage": 0,
        "last_interaction_at": null
    }',

    -- Flexible metadata
    metadata JSONB DEFAULT '{}',

    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tasks_user ON tasks(user_phone);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_remind_at ON tasks(remind_at);
CREATE INDEX IF NOT EXISTS idx_tasks_due_date ON tasks(due_date);

-- ============================================
-- RECURRING TASKS TABLE (habits, routines)
-- ============================================
CREATE TABLE IF NOT EXISTS recurring_tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_phone VARCHAR(20) NOT NULL,
    title VARCHAR(500) NOT NULL,
    description TEXT,
    status VARCHAR(20) DEFAULT 'active' CHECK (status IN ('active', 'paused', 'dropped')),

    -- Frequency settings
    frequency VARCHAR(20) DEFAULT 'daily' CHECK (frequency IN ('daily', 'weekly', 'custom')),
    times_per_day INT DEFAULT 1,  -- 4 for water, 1 for gym
    schedule JSONB DEFAULT '{
        "times": ["09:00"],
        "days": [1, 2, 3, 4, 5, 6, 7]
    }',  -- days: 1=Mon, 7=Sun

    -- Streaks
    streak_current INT DEFAULT 0,
    streak_best INT DEFAULT 0,

    -- Optional metric tracking (steps, glasses, pages)
    metric JSONB,  -- {"type": "count", "unit": "glasses", "target": 8}

    -- Vector reference
    vector_id VARCHAR(255),

    -- Timing
    created_at TIMESTAMPTZ DEFAULT NOW(),
    next_reminder_at TIMESTAMPTZ,  -- computed: next scheduled time

    -- Flexible metadata
    metadata JSONB DEFAULT '{}',

    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_recurring_tasks_user ON recurring_tasks(user_phone);
CREATE INDEX IF NOT EXISTS idx_recurring_tasks_status ON recurring_tasks(status);
CREATE INDEX IF NOT EXISTS idx_recurring_tasks_next ON recurring_tasks(next_reminder_at);

-- ============================================
-- RECURRING TASK LOGS (daily tracking)
-- ============================================
CREATE TABLE IF NOT EXISTS recurring_task_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    recurring_task_id UUID NOT NULL REFERENCES recurring_tasks(id) ON DELETE CASCADE,
    user_phone VARCHAR(20) NOT NULL,  -- denormalized for easy queries
    date DATE NOT NULL,

    scheduled_count INT DEFAULT 0,   -- how many reminders scheduled
    completed_count INT DEFAULT 0,   -- how many marked done
    skipped BOOLEAN DEFAULT FALSE,   -- user said "skip today"

    metric_values JSONB,  -- [{"time": "09:00", "value": 6000}, ...]
    streak_maintained BOOLEAN,

    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_recurring_logs_task ON recurring_task_logs(recurring_task_id);
CREATE INDEX IF NOT EXISTS idx_recurring_logs_user_date ON recurring_task_logs(user_phone, date);
CREATE UNIQUE INDEX IF NOT EXISTS idx_recurring_logs_unique ON recurring_task_logs(recurring_task_id, date);

-- ============================================
-- TASK INTERACTIONS (every touchpoint)
-- ============================================
CREATE TABLE IF NOT EXISTS task_interactions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_phone VARCHAR(20) NOT NULL,

    -- Link to task (one of these will be set)
    task_id UUID REFERENCES tasks(id) ON DELETE SET NULL,
    recurring_task_id UUID REFERENCES recurring_tasks(id) ON DELETE SET NULL,

    -- Interaction type
    type VARCHAR(30) NOT NULL CHECK (type IN (
        'created', 'reminded', 'checkin', 'response',
        'completed', 'snoozed', 'skipped', 'dropped'
    )),

    -- What was said
    donna_message TEXT,
    user_message TEXT,

    -- Context
    context VARCHAR(30) CHECK (context IN (
        'morning_brief', 'evening_checkin', 'random_checkin',
        'direct', 'scheduled', 'webhook'
    )),

    -- Vector for insights
    vector_id VARCHAR(255),

    timestamp TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_interactions_user ON task_interactions(user_phone);
CREATE INDEX IF NOT EXISTS idx_interactions_task ON task_interactions(task_id);
CREATE INDEX IF NOT EXISTS idx_interactions_recurring ON task_interactions(recurring_task_id);
CREATE INDEX IF NOT EXISTS idx_interactions_timestamp ON task_interactions(timestamp);
CREATE INDEX IF NOT EXISTS idx_interactions_type ON task_interactions(type);

-- ============================================
-- CONVERSATIONS (all chats)
-- ============================================
CREATE TABLE IF NOT EXISTS conversations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_phone VARCHAR(20) NOT NULL,
    direction VARCHAR(10) NOT NULL CHECK (direction IN ('incoming', 'outgoing')),
    message TEXT NOT NULL,

    -- Link to related task (optional)
    related_task_id UUID REFERENCES tasks(id) ON DELETE SET NULL,
    related_recurring_task_id UUID REFERENCES recurring_tasks(id) ON DELETE SET NULL,

    -- Vector for semantic search
    vector_id VARCHAR(255),

    -- Metadata
    metadata JSONB DEFAULT '{}',

    timestamp TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_conversations_user ON conversations(user_phone);
CREATE INDEX IF NOT EXISTS idx_conversations_timestamp ON conversations(timestamp);
CREATE INDEX IF NOT EXISTS idx_conversations_direction ON conversations(direction);

-- ============================================
-- BRIEFS (morning/evening summaries sent)
-- ============================================
CREATE TABLE IF NOT EXISTS briefs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_phone VARCHAR(20) NOT NULL,
    type VARCHAR(20) NOT NULL CHECK (type IN ('morning', 'evening', 'weekly')),

    -- What was included
    task_ids UUID[],
    recurring_task_ids UUID[],

    -- Content hash (avoid storing exact text, just for dedup)
    content_summary TEXT,

    -- Did user engage?
    user_engaged BOOLEAN DEFAULT FALSE,
    response_time_seconds INT,  -- how fast they responded

    sent_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_briefs_user ON briefs(user_phone);
CREATE INDEX IF NOT EXISTS idx_briefs_type ON briefs(type);
CREATE INDEX IF NOT EXISTS idx_briefs_sent ON briefs(sent_at);

-- ============================================
-- SCHEDULED TRIGGERS (for webhook triggers)
-- ============================================
CREATE TABLE IF NOT EXISTS scheduled_triggers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_phone VARCHAR(20) NOT NULL,

    -- What to trigger
    trigger_type VARCHAR(30) NOT NULL CHECK (trigger_type IN (
        'task_reminder', 'task_checkin',
        'recurring_reminder', 'recurring_checkin',
        'morning_brief', 'evening_checkin'
    )),

    -- Reference
    task_id UUID REFERENCES tasks(id) ON DELETE CASCADE,
    recurring_task_id UUID REFERENCES recurring_tasks(id) ON DELETE CASCADE,

    -- When to trigger
    trigger_at TIMESTAMPTZ NOT NULL,

    -- Status
    status VARCHAR(20) DEFAULT 'pending' CHECK (status IN ('pending', 'triggered', 'cancelled')),
    triggered_at TIMESTAMPTZ,

    -- Metadata
    metadata JSONB DEFAULT '{}',

    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_triggers_pending ON scheduled_triggers(trigger_at) WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS idx_triggers_user ON scheduled_triggers(user_phone);
CREATE INDEX IF NOT EXISTS idx_triggers_task ON scheduled_triggers(task_id);
CREATE INDEX IF NOT EXISTS idx_triggers_recurring ON scheduled_triggers(recurring_task_id);

-- ============================================
-- KEEP EXISTING TABLES (for backward compatibility)
-- ============================================

-- Keep 'schedule' table for now (migrate data later)
-- Keep 'chat' table for now (migrate to conversations later)
-- Keep 'memory' table for now (still used by Pinecone sync)
-- Keep 'entities' table (useful for contact lookup)

-- ============================================
-- HELPER FUNCTIONS
-- ============================================

-- Function to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Triggers for updated_at
DROP TRIGGER IF EXISTS update_users_updated_at ON users;
CREATE TRIGGER update_users_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_tasks_updated_at ON tasks;
CREATE TRIGGER update_tasks_updated_at
    BEFORE UPDATE ON tasks
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_recurring_tasks_updated_at ON recurring_tasks;
CREATE TRIGGER update_recurring_tasks_updated_at
    BEFORE UPDATE ON recurring_tasks
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================
-- GRANT PERMISSIONS
-- ============================================
-- After running this SQL:
-- 1. Go to Hasura Console > Data > Track Tables (track all new tables)
-- 2. Set up permissions for each table (allow admin role full access)
-- 3. Create scheduled event for trigger polling (or use Nhost events)

-- ============================================
-- MIGRATION NOTES
-- ============================================
-- To migrate existing reminders from 'schedule' table:
--
-- INSERT INTO tasks (user_phone, title, status, remind_at, created_at)
-- SELECT
--     phone_no,
--     reminder,
--     CASE WHEN reminder_sent THEN 'completed' ELSE 'pending' END,
--     reminder_time,
--     created_at
-- FROM schedule
-- WHERE reminder IS NOT NULL;
