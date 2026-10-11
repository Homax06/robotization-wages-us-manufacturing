# Reproducible environment for the robotization-wages pipeline.
# Build:  docker build -t robots-wages .
# Run:    docker run --rm -v "$(pwd)/results:/app/results" robots-wages
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MPLBACKEND=Agg

WORKDIR /app

# Dependencies first: this layer is cached until requirements.txt changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY config.yaml pytest.ini ./
COPY src ./src
COPY tests ./tests
COPY data/sample ./data/sample

# Default: run the pipeline on the sample data (writes tables, plot and log to /app/results).
CMD ["python", "-m", "src.main", "--config", "config.yaml"]
