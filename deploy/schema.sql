-- Donna AI Database Schema
-- Run this in Nhost SQL editor (Hasura Console > Data > SQL)

-- Entities table (people, places, things the user mentions)
CREATE TABLE IF NOT EXISTS entities (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_phone VARCHAR(20) NOT NULL,
    type VARCHAR(50) NOT NULL,           -- person, place, organization, thing
    name VARCHAR(255) NOT NULL,
    attributes JSONB DEFAULT '{}',        -- phone, email, relationship, address, etc.
    last_mentioned TIMESTAMPTZ DEFAULT NOW(),
    mention_count INT DEFAULT 1,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Unique constraint for upserts (one entity per user+type+name)
ALTER TABLE entities ADD CONSTRAINT entities_user_phone_type_name_key
    UNIQUE (user_phone, type, name);

-- Indexes for entities
CREATE INDEX IF NOT EXISTS idx_entities_user ON entities(user_phone);
CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(type);
CREATE INDEX IF NOT EXISTS idx_entities_name ON entities(name);

-- Memories table (tracks what's in Pinecone for reference)
CREATE TABLE IF NOT EXISTS memories (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_phone VARCHAR(20) NOT NULL,
    pinecone_id VARCHAR(255),             -- reference to vector in Pinecone
    category VARCHAR(50) NOT NULL,        -- entity, preference, fact, event, conversation
    content TEXT NOT NULL,                -- the actual memory text
    importance FLOAT DEFAULT 0.5,         -- 0-1 score
    source_type VARCHAR(50),              -- conversation, import, manual
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for memories
CREATE INDEX IF NOT EXISTS idx_memories_user ON memories(user_phone);
CREATE INDEX IF NOT EXISTS idx_memories_category ON memories(category);

-- Conversations table (groups of messages)
CREATE TABLE IF NOT EXISTS conversations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_phone VARCHAR(20) NOT NULL,
    started_at TIMESTAMPTZ DEFAULT NOW(),
    ended_at TIMESTAMPTZ,
    message_count INT DEFAULT 0,
    summary TEXT,                         -- LLM-generated summary
    extracted_memories JSONB,             -- what was learned from this conversation
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Index for conversations
CREATE INDEX IF NOT EXISTS idx_conversations_user ON conversations(user_phone);
CREATE INDEX IF NOT EXISTS idx_conversations_started ON conversations(started_at);

-- Grant permissions (Hasura needs these)
-- After creating tables, go to Hasura Console > Data > Track Tables
-- Then set permissions for the 'admin' role
