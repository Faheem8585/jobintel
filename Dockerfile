FROM python:3.11-slim

LABEL maintainer="Faheem"
LABEL description="JobIntel — Intelligent Job Search & Application Tracking Skill"
LABEL version="1.0.0"

# System dependencies for lxml / nltk
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libxml2-dev \
    libxslt1-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first (layer cache optimisation)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Download NLTK data at build time so the container is self-contained
RUN python -c "import nltk; nltk.download('punkt'); nltk.download('stopwords'); nltk.download('averaged_perceptron_tagger')"

# Copy source
COPY . .

# Persistent data volumes
VOLUME ["/app/data", "/app/logs"]

# Create runtime directories
RUN mkdir -p data/backups logs

# Non-root user for security
RUN useradd -m -u 1000 jobintel && chown -R jobintel:jobintel /app
USER jobintel

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

CMD ["python", "skill.py"]
