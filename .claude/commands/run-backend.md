# run-backend
Start the FastAPI backend server on port 8001

1. Check `backend/.env` exists with `OPENAI_API_KEY` and `KB_PIPELINE_URL` set
2. Install deps: `pip install -r backend/requirements.txt`
3. Start server: `cd backend && python -m uvicorn server:app --reload --port 8001`
4. Server will be at `http://localhost:8001`
5. API docs at `http://localhost:8001/docs`
