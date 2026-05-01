FROM python:3.12-slim
WORKDIR /app
COPY common/ /app/common/
COPY pincode-api/ /app/
RUN pip install --no-cache-dir -r requirements.txt
EXPOSE 8002
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8002"]
