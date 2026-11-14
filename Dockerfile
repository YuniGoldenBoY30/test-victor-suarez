# Imagen del backend (FastAPI + DuckDB). Nunca incluye .env: la configuracion llega por env_file/entorno.
FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Usuario sin privilegios
RUN useradd --create-home --uid 10001 appuser

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY core ./core
COPY etl ./etl
COPY app ./app
COPY sql ./sql
COPY data/pedidos_raw.csv ./data/pedidos_raw.csv

# data/ debe poder escribirse (la base DuckDB se genera ahi; en compose es un volumen)
RUN chown -R appuser:appuser /app/data
USER appuser

EXPOSE 8000

# Construye la base solo si falta y arranca la API
CMD ["sh", "-c", "python -m etl --si-falta && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
