FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    DATABASE_PATH=/app/data/bot.sqlite3 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/data && chmod 700 /app/data
VOLUME ["/app/data"]

EXPOSE 8080

CMD ["uvicorn", "agromat_help_desk_bot.main:app", "--host", "0.0.0.0", "--port", "8080"]
