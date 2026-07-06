# AI Chatbot SaaS Platform - Backend


This is the backend API service for the AI Chatbot SaaS Platform, built using **FastAPI** and **Python**.

## Folder Structure

Following a scalable enterprise SaaS architecture, the `backend/` directory is organized as follows:

```
backend/
├── app/
│   ├── api/             # API Router & Route Handlers (separated by version)
│   │   └── v1/          # API v1 routes (e.g., chats, billing, users)
│   ├── core/            # Core Config, Security, DB initialization
│   ├── crud/            # Database Create, Read, Update, Delete helpers
│   ├── models/          # SQLAlchemy/SQLModel DB schemas
│   ├── schemas/         # Pydantic Request/Response validation schemas
│   ├── services/        # Business logic layer (LLM client, auth logic, payments)
│   ├── dependencies.py  # Common FastAPI dependencies (auth, db connections)
│   └── main.py          # FastAPI application entrypoint
├── tests/               # Test suites (unit and integration tests)
├── .env.example         # Template for environment configuration
└── requirements.txt     # Python dependency list
```

## Getting Started

### Prerequisites

Ensure you have Python 3.10+ installed.

### Installation

1. Navigate to the backend directory:
   ```bash
   cd backend
   ```
2. Create a virtual environment:
   ```bash
   python -m venv venv
   ```
3. Activate the virtual environment:
   - On Windows:
     ```bash
     .\venv\Scripts\activate
     ```
   - On macOS/Linux:
     ```bash
     source venv/bin/activate
     ```
4. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

### Running Locally

To run the FastAPI server with auto-reload:

```bash
uvicorn app.main:app --reload
```

The API will be available at [http://localhost:8000](http://localhost:8000).
Interactive API documentation will be available at [http://localhost:8000/api/v1/docs](http://localhost:8000/api/v1/docs).

### Running Tests

To run the test suite:

```bash
pytest
```
