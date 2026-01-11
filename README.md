# Donna AI - Your Executive Assistant

Donna is an AI executive assistant that coordinates your life via WhatsApp. She acts like a cofounder, not a servant - opinionated, proactive, and genuinely invested in your success.

## Features

- **WhatsApp Native** - Chat naturally via WhatsApp
- **Smart Reminders** - "Remind me to call Mom at 3pm"
- **Long-term Memory** - Remembers birthdays, preferences, relationships (Pinecone)
- **Calendar Integration** - View and create Google Calendar events (Composio)
- **Email Integration** - Search, draft, send emails (Gmail via Composio)
- **Proactive** - Pushes back when your schedule is overloaded

## Architecture

```
WhatsApp → n8n (relay) → Donna API → Response
                              ↓
                         Nhost (DB)
                         Pinecone (Memory)
                         Composio (Calendar/Email)
```

## Quick Start

### 1. Clone and Setup

```bash
git clone <your-repo-url> donna-ai
cd donna-ai
cp .env.example .env
```

### 2. Configure Environment

Edit `.env` with your credentials:

```env
# Required
OPENROUTER_API_KEY=your_key
NHOST_GRAPHQL_ENDPOINT=https://your-project.hasura.region.nhost.run/v1/graphql
NHOST_ADMIN_SECRET=your_secret
WHATSAPP_PHONE_NUMBER_ID=806507515890557
WHATSAPP_ACCESS_TOKEN=your_token

# Optional (for full features)
PINECONE_API_KEY=your_key
PINECONE_INDEX=donna-memory
COMPOSIO_API_KEY=your_key
```

### 3. Install Dependencies

```bash
# Python backend
cd server
python3.10 -m venv .venv
source .venv/bin/activate  # or `.venv\Scripts\activate` on Windows
pip install -r requirements.txt
```

### 4. Run the Server

```bash
# From server directory
uvicorn app:app --host 0.0.0.0 --port 8001 --reload
```

Server runs at `http://localhost:8001`
Docs at `http://localhost:8001/docs`

### 5. Setup n8n Relay

1. Import `n8n-relay-workflow.json` into your n8n instance
2. Set environment variable `DONNA_API_URL=https://your-donna-server.com`
3. Update the Meta webhook verify token
4. Activate the workflow

### 6. Configure Meta WhatsApp

1. Go to Meta Business Suite → WhatsApp → API Setup
2. Set webhook URL: `https://your-n8n-url/webhook/whatsappmeta`
3. Set verify token: `my_secret_token` (or whatever you set in n8n)
4. Subscribe to: `messages`

## API Endpoints

### WhatsApp Webhook
```
POST /api/v1/whatsapp/webhook
```
Receives messages from n8n relay. Returns immediately, processes async.

Request body:
```json
{
  "phone": "919008227180",
  "message": "Remind me to call mom at 3pm",
  "profile_name": "John Doe"
}
```

### Health Check
```
GET /api/v1/whatsapp/health
```

## Donna's Personality

Donna is:
- **Sharp** - Gets things done efficiently
- **Warm** - Genuinely cares about your success
- **Opinionated** - Pushes back when needed
- **Proactive** - Anticipates your needs

She won't say:
- "Certainly!"
- "I'd be happy to help!"
- "Let me know if you need anything else"

She will say:
- "Got it"
- "Done"
- "You sure? You already have 5 meetings Thursday."

## Database Schema (Nhost)

The app expects these tables in your Nhost database:

### user_phone_no
```sql
- id (uuid)
- phone_no (text, unique)
- name (text)
- email (text)
- user_context (text)
- default_reminder_method (text, default 'whatsapp')
- timezone (text, default 'Asia/Kolkata')
- daily_checkin_enabled (boolean)
- daily_checkin_time (time)
- pin_status (text)
- onboarding (jsonb)
```

### schedule
```sql
- id (uuid)
- user_id (uuid)
- phone_number (text)
- call_time (timestamptz)
- context (text)
- call_status (text)
- task_status (text)
- habit_type (text)
- importance (text)
- reminder_method (text)
- rich_context (jsonb)
- follow_up_time (timestamptz)
- follow_up_count (int)
- reminder_sent (boolean)
- is_recurring (boolean)
- recurrence_rule (text)
```

### chats
```sql
- id (uuid)
- phone_no (text)
- chat (text)
- type (text) -- 'received' or 'sent'
- created_at (timestamptz)
```

## Deployment

### Railway (Recommended)

1. Push to GitHub
2. Connect Railway to repo
3. Add environment variables
4. Deploy

### Docker

```dockerfile
FROM python:3.10-slim
WORKDIR /app
COPY server/ .
RUN pip install -r requirements.txt
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8001"]
```

## Development

```bash
# Run with auto-reload
cd server
uvicorn app:app --reload --port 8001

# Test webhook locally
curl -X POST http://localhost:8001/api/v1/whatsapp/webhook \
  -H "Content-Type: application/json" \
  -d '{"phone":"919008227180","message":"hi","profile_name":"Test"}'
```

## Project Structure

```
donna-ai/
├── server/
│   ├── agents/
│   │   ├── donna/           # Main Donna agent
│   │   │   ├── agent.py     # Tool definitions & execution
│   │   │   ├── runtime.py   # LLM interaction loop
│   │   │   └── system_prompt.md
│   │   ├── interaction_agent/  # Legacy OpenPoke agent
│   │   └── execution_agent/    # Legacy OpenPoke agents
│   ├── services/
│   │   ├── database/        # Nhost GraphQL client
│   │   ├── whatsapp/        # Meta WhatsApp API
│   │   ├── memory/          # Pinecone vector store
│   │   ├── calendar/        # Google Calendar via Composio
│   │   └── scheduler/       # Reminder firing
│   ├── routes/
│   │   └── whatsapp.py      # Webhook endpoint
│   ├── config.py
│   ├── app.py
│   └── requirements.txt
├── n8n-relay-workflow.json  # Import this into n8n
├── .env.example
└── README.md
```

## License

MIT
