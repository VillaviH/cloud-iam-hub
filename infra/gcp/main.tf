terraform {
  required_version = ">= 1.5.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  # Backend local por defecto (state se ignora vía .gitignore).
}

provider "google" {
  project = var.gcp_project_id
  region  = var.gcp_region
}

resource "random_id" "suffix" {
  byte_length = 3
}

# ---------------------------------------------------------------------------
# APIs necesarias: Firestore (estado del hub), IAM + Resource Manager
# (lo que ejercita el GcpAdapter con getIamPolicy/setIamPolicy + etag),
# Cloud Run (para desplegar el backend) y Storage (frontend estático).
# ---------------------------------------------------------------------------

locals {
  required_apis = [
    "firestore.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "run.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "storage.googleapis.com",
    "artifactregistry.googleapis.com",
    "secretmanager.googleapis.com",
    "cloudbuild.googleapis.com",
  ]
}

resource "google_project_service" "apis" {
  for_each = toset(local.required_apis)

  project            = var.gcp_project_id
  service            = each.value
  disable_on_destroy = false
}

# ---------------------------------------------------------------------------
# Firestore — Identity / Role / Assignment / Audit
# ---------------------------------------------------------------------------

resource "google_firestore_database" "database" {
  project     = var.gcp_project_id
  name        = "(default)"
  location_id = var.firestore_location
  type        = "FIRESTORE_NATIVE"

  depends_on = [google_project_service.apis]
}

# ---------------------------------------------------------------------------
# Frontend estático — el proyecto se presenta en un DevFest de GCP, así
# que todo (incluido el frontend) vive en Google Cloud: un bucket de
# Cloud Storage con hosting de sitio web estático, acceso público de
# solo lectura.
# ---------------------------------------------------------------------------

resource "google_storage_bucket" "frontend" {
  project                     = var.gcp_project_id
  name                         = "${var.project_name}-frontend-${random_id.suffix.hex}"
  location                     = var.gcp_region
  uniform_bucket_level_access = true
  force_destroy                = true

  website {
    main_page_suffix = "index.html"
    not_found_page   = "index.html"
  }

  depends_on = [google_project_service.apis]
}

resource "google_storage_bucket_iam_member" "frontend_public_read" {
  bucket = google_storage_bucket.frontend.name
  role   = "roles/storage.objectViewer"
  member = "allUsers"
}

# ---------------------------------------------------------------------------
# Service Account dedicado para el backend (control plane). El backend
# nunca debe correr con tu usuario personal — usa esta identidad acotada.
# ---------------------------------------------------------------------------

resource "google_service_account" "backend" {
  project      = var.gcp_project_id
  account_id   = "${var.project_name}-backend"
  display_name = "cloud-iam-hub backend (control plane)"
}

resource "google_project_iam_member" "backend_firestore" {
  project = var.gcp_project_id
  role    = "roles/datastore.user"
  member  = "serviceAccount:${google_service_account.backend.email}"
}

# Permiso para leer/escribir la IAM policy del PROPIO proyecto — esto es
# lo que ejercita el GcpAdapter (getIamPolicy -> mutar -> setIamPolicy con etag).
resource "google_project_iam_member" "backend_security_admin" {
  project = var.gcp_project_id
  role    = "roles/resourcemanager.projectIamAdmin"
  member  = "serviceAccount:${google_service_account.backend.email}"
}

resource "google_service_account_key" "backend_key" {
  service_account_id = google_service_account.backend.name
}

# ---------------------------------------------------------------------------
# Principal de demo — el recurso "gobernado" real donde el GcpAdapter
# agrega/quita bindings en cada onboarding/offboarding.
# ---------------------------------------------------------------------------

resource "google_service_account" "demo_target_principal" {
  project      = var.gcp_project_id
  account_id   = "${var.project_name}-demo-target"
  display_name = "Principal de ejemplo gobernado por el demo (onboarding/offboarding)"
}
