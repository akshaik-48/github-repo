FROM python:3.11-slim

WORKDIR /home/app/web

# Install system deps needed by psycopg2 and other packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code and rule files
COPY app/ app/
COPY rules/ rules/

# Default environment — can be overridden at runtime via Agent Hub credentials
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    POST_COMMENTS_ENABLED=false \
    OLLAMA_ENABLED=false

# MCP stdio server entry point
ENTRYPOINT ["python", "-m", "app.mcp_server"]
