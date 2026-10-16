FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY src/ ./src/
RUN pip install --no-cache-dir .
COPY dashboard.py ./
RUN mkdir -p /app/state
ENV PYTHONUNBUFFERED=1
CMD ["paperbot", "run"]
