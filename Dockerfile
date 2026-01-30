FROM python:3.10-slim

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONPATH=/app

WORKDIR /app

# System deps:
# - curl: healthcheck
# - libgl1/libglib2.0-0: opencv runtime deps
RUN apt-get update \
  && apt-get install -y --no-install-recommends \
    curl \
    libgl1 \
    libglib2.0-0 \
  && rm -rf /var/lib/apt/lists/*

# Python deps
COPY homework_agent/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# App code
COPY homework_agent/ ./homework_agent/
COPY migrations/ ./migrations/
COPY supabase/ ./supabase/
COPY scripts/ ./scripts/

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -fsS http://localhost:8000/healthz || exit 1

CMD ["uvicorn", "homework_agent.main:app", "--host", "0.0.0.0", "--port", "8000"]
