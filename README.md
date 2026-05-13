# SG Property Agent

A conversational AI agent for Singapore property advice. Combines the KB-Pipeline retrieval API with Claude's reasoning to answer questions about ABSD, HDB eligibility, stamp duty, and more.

## Architecture

```
Frontend (React/Vite @ :5173)
  ↓
Backend (FastAPI @ :8001)
  ↓
KB-Pipeline API (@ :8000)
```

## Setup

### Backend

```bash
cd backend
pip install -r requirements.txt
cp ../.env.example .env
# Edit .env with your ANTHROPIC_API_KEY
```

### Frontend

```bash
cd frontend
npm install
```

## Running

### 1. Start KB-Pipeline

```bash
cd c:\GEEMETH\N\KB-Pipeline
docker compose up -d
```

### 2. Start Backend

```bash
cd sg-property-agent\backend
python -m uvicorn server:app --reload --port 8001
```

### 3. Start Frontend

```bash
cd sg-property-agent\frontend
npm run dev
```

Open `http://localhost:5173` in your browser.

## How It Works

1. User types a question in the React UI
2. Frontend sends POST to `/chat` on backend
3. Backend calls KB-Pipeline `/retrieve` to fetch relevant chunks
4. Backend formats chunks as context and sends to Claude
5. Claude generates answer grounded in the context
6. Answer is displayed in the UI
7. Conversation history is maintained for follow-ups

## Features

- **Multi-turn conversation** — maintains history across messages
- **Grounded answers** — responses cite official government sources
- **Error handling** — gracefully handles KB-Pipeline unavailability
- **Reset button** — clears conversation history anytime
- **Hybrid search** — uses both vector + BM25 for better results

## Example Questions

- "What is ABSD for a PR buying a condo?"
- "What if they already own one property?"
- "What is the stamp duty for HDB buyers?"
- "Am I eligible for HDB as a PR?"

## Tech Stack

- **Backend:** FastAPI, Anthropic Claude, httpx
- **Frontend:** React 18, Vite
- **Retrieval:** KB-Pipeline (separate project)
