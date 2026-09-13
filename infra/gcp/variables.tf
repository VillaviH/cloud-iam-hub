variable "gcp_project_id" {
  description = "ID del proyecto GCP donde vive el control plane (Cloud Run, Firestore, IAM) y el frontend (Cloud Storage)."
  type        = string
}

variable "gcp_region" {
  description = "Región por defecto para recursos de GCP."
  type        = string
  default     = "us-central1"
}

variable "firestore_location" {
  description = "Ubicación multi-región o regional para la base Firestore."
  type        = string
  default     = "nam5"
}

variable "project_name" {
  description = "Prefijo usado para nombrar recursos del proyecto."
  type        = string
  default     = "cloud-iam-hub"
}

variable "backend_image" {
  description = <<-EOT
    Imagen de contenedor para el servicio Cloud Run del backend.
    Por defecto usa la imagen de ejemplo pública de Cloud Run ("Hello")
    para que el primer `terraform apply` no falle antes de construir la
    imagen real. Reemplázala con:
      gcloud builds submit backend/ --tag <region>-docker.pkg.dev/<project>/cloud-iam-hub/backend:latest
      gcloud run deploy cloud-iam-hub-backend --image <esa-imagen> --region <region>
    (Terraform ignora cambios posteriores en este campo, ver cloud_run.tf).
  EOT
  type        = string
  default     = "us-docker.pkg.dev/cloudrun/container/hello"
}

variable "cloud_iam_mode" {
  description = "Modo del backend en Cloud Run: sandbox (mock, sin llamadas reales) o live."
  type        = string
  default     = "sandbox"
}
