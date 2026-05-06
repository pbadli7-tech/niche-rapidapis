FROM python:3.12-slim
WORKDIR /app
COPY common/ /app/common/
COPY stock-market-api/ /app/
RUN pip install --no-cache-dir -r requirements.txt
EXPOSE 8008
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8008"]
