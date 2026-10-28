FROM python:3.12-slim
WORKDIR /app
COPY server.py ./
COPY web ./web
ENV DB_PATH=/app/data/clash.db PORT=8080 PYTHONUNBUFFERED=1
EXPOSE 8080
CMD ["python3", "server.py"]
