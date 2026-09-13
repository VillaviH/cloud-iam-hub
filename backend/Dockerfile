# Imagen del backend para Cloud Run.
#
# Build + push (usa Cloud Build, no requiere Docker local):
#   gcloud builds submit . \
#     --tag <region>-docker.pkg.dev/<project>/cloud-iam-hub/backend:latest
#
# Deploy:
#   gcloud run deploy cloud-iam-hub-backend \
#     --image <region>-docker.pkg.dev/<project>/cloud-iam-hub/backend:latest \
#     --region <region>

FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

ENV PORT=8080
EXPOSE 8080

CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT}
