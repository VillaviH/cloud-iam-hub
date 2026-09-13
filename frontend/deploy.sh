#!/usr/bin/env bash
# Sube el frontend estático al bucket de Cloud Storage creado por Terraform
# (infra/gcp -> google_storage_bucket.frontend). Requiere haber corrido
# `terraform apply` en infra/gcp antes.
#
# Uso:
#   ./deploy.sh <nombre-del-bucket>
#
# El nombre del bucket se puede obtener con:
#   terraform -chdir=../infra/gcp output -raw frontend_bucket_name

set -euo pipefail

BUCKET_NAME="${1:-}"

if [[ -z "$BUCKET_NAME" ]]; then
  echo "Uso: ./deploy.sh <nombre-del-bucket>"
  echo "Obtén el nombre con: terraform -chdir=../infra/gcp output -raw frontend_bucket_name"
  exit 1
fi

echo "Subiendo frontend a gs://${BUCKET_NAME}/ ..."
gcloud storage cp index.html "gs://${BUCKET_NAME}/index.html"

echo "Listo. URL pública:"
echo "https://storage.googleapis.com/${BUCKET_NAME}/index.html"
