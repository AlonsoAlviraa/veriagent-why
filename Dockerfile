FROM python:3.13-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends nodejs && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN mkdir -p /app/logs && python scripts/make_data.py
ENV SAMPLE_MODE=true PORT=8000
EXPOSE 8000
CMD ["python", "run.py", "--serve"]
