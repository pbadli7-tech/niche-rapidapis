FROM python:3.12-slim
WORKDIR /app
COPY common/ /app/common/
COPY email-validator-api/ /app/
RUN pip install --no-cache-dir -r requirements.txt
EXPOSE 8010
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8010"]
