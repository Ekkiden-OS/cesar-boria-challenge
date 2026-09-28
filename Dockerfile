FROM python:3.12.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt

COPY powerplant ./powerplant

EXPOSE 8888

CMD ["python", "-m", "uvicorn", "powerplant.main:app", "--host", "0.0.0.0", "--port", "8888"]
