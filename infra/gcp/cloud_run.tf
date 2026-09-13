# ---------------------------------------------------------------------------
# Despliegue del backend a Cloud Run — todo vive en GCP (control plane +
# frontend + backend), coherente con que la charla es en un DevFest de GCP.
#
# Flujo de despliegue real:
#   1. `terraform apply` crea el repo de Artifact Registry, el secret de
#      Secret Manager y el servicio Cloud Run con una imagen placeholder
#      ("Hello" de Cloud Run) para que el primer apply no falle por falta
#      de imagen.
#   2. Se construye y publica la imagen real del backend:
#        gcloud builds submit backend/ \
#          --tag <region>-docker.pkg.dev/<project>/cloud-iam-hub/backend:latest
#   3. Se actualiza el servicio con esa imagen:
#        gcloud run deploy cloud-iam-hub-backend \
#          --image <region>-docker.pkg.dev/<project>/cloud-iam-hub/backend:latest \
#          --region <region>
#   4. Despliegues posteriores (paso 2+3) no pasan por Terraform — el
#      recurso ignora cambios en `image` a propósito (ver lifecycle abajo),
#      así `gcloud run deploy` y `terraform apply` no se pelean por quién
#      manda en la imagen.
# ---------------------------------------------------------------------------

resource "google_artifact_registry_repository" "backend" {
  project       = var.gcp_project_id
  location      = var.gcp_region
  repository_id = "${var.project_name}"
  format        = "DOCKER"
  description   = "Imágenes del backend de cloud-iam-hub"

  depends_on = [google_project_service.apis]
}

# ---------------------------------------------------------------------------
# Secret Manager — API_SHARED_SECRET. Se genera automáticamente (nunca se
# escribe a mano ni se commitea) y el backend lo lee como variable de
# entorno inyectada por Cloud Run desde el secret. Esto es lo que protege
# POST /onboard, POST /offboard y GET /audit de ser invocados por
# cualquiera que encuentre la URL pública del servicio.
# ---------------------------------------------------------------------------

resource "random_password" "api_shared_secret" {
  length  = 40
  special = false
}

resource "google_secret_manager_secret" "api_shared_secret" {
  project   = var.gcp_project_id
  secret_id = "${var.project_name}-api-shared-secret"

  replication {
    auto {}
  }

  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret_version" "api_shared_secret" {
  secret      = google_secret_manager_secret.api_shared_secret.id
  secret_data = random_password.api_shared_secret.result
}

resource "google_secret_manager_secret_iam_member" "backend_can_read_secret" {
  project   = var.gcp_project_id
  secret_id = google_secret_manager_secret.api_shared_secret.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.backend.email}"
}

# ---------------------------------------------------------------------------
# Cloud Run — el backend (FastAPI). Se invoca sin autenticación IAM
# (allUsers) porque el frontend estático llama directo a esta URL desde el
# navegador de cualquier asistente a la demo; la protección real es el
# header `X-Api-Key` validado dentro de la propia app (ver
# backend/app/routers/identity.py -> require_api_key). Por eso el secret
# de arriba es obligatorio en cualquier despliegue que no sea localhost.
# ---------------------------------------------------------------------------

resource "google_cloud_run_v2_service" "backend" {
  project  = var.gcp_project_id
  name     = "${var.project_name}-backend"
  location = var.gcp_region

  template {
    service_account = google_service_account.backend.email

    containers {
      # Imagen placeholder para el primer apply. Se reemplaza con
      # `gcloud run deploy --image ...` (ver comentario arriba); Terraform
      # ignora cambios posteriores en `image` (lifecycle.ignore_changes).
      image = var.backend_image

      env {
        name  = "CLOUD_IAM_MODE"
        value = var.cloud_iam_mode
      }
      env {
        name  = "GCP_PROJECT_ID"
        value = var.gcp_project_id
      }
      env {
        name  = "GCP_DEMO_TARGET_RESOURCE_MEMBER"
        value = google_service_account.demo_target_principal.email
      }
      env {
        name = "API_SHARED_SECRET"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.api_shared_secret.secret_id
            version = "latest"
          }
        }
      }
      env {
        name  = "API_CORS_ORIGINS"
        value = "https://storage.googleapis.com"
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
      }
    }
  }

  depends_on = [google_project_service.apis]

  lifecycle {
    ignore_changes = [
      template[0].containers[0].image,
    ]
  }
}

resource "google_cloud_run_v2_service_iam_member" "public_invoker" {
  project  = var.gcp_project_id
  location = var.gcp_region
  name     = google_cloud_run_v2_service.backend.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}
