FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY cli.py .

# Generated test output directory (volume-mounted by docker-compose)
RUN mkdir -p /app/generated-tests

CMD ["python", "cli.py"]
