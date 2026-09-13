output "backend_service_account_email" {
  description = "Service account que debe usar el backend (control plane)."
  value       = google_service_account.backend.email
}

output "backend_service_account_key" {
  description = "Clave JSON (base64) del service account del backend. Decodificar y guardar como backend/gcp-sa.json (gitignored)."
  value       = google_service_account_key.backend_key.private_key
  sensitive   = true
}

output "demo_target_principal_email" {
  description = "Service account de ejemplo sobre el cual el GcpAdapter agrega/quita bindings."
  value       = google_service_account.demo_target_principal.email
}

output "firestore_database_name" {
  description = "Nombre de la base Firestore usada por el control plane."
  value       = google_firestore_database.database.name
}

output "frontend_bucket_name" {
  description = "Nombre del bucket de Cloud Storage con el frontend estático."
  value       = google_storage_bucket.frontend.name
}

output "frontend_url" {
  description = "URL pública del frontend (Cloud Storage website hosting)."
  value       = "https://storage.googleapis.com/${google_storage_bucket.frontend.name}/index.html"
}

output "backend_url" {
  description = "URL pública del servicio Cloud Run del backend. Pégala en el frontend como 'URL del backend'."
  value       = google_cloud_run_v2_service.backend.uri
}

output "api_shared_secret" {
  description = <<-EOT
    Valor de API_SHARED_SECRET generado automáticamente. Compártelo solo
    con quien deba disparar la demo (se pega en el campo 'API Key' del
    frontend). NUNCA lo commitees ni lo publiques en el repo.
  EOT
  value       = random_password.api_shared_secret.result
  sensitive   = true
}

output "artifact_registry_repo" {
  description = "Repositorio de Artifact Registry para la imagen del backend."
  value       = google_artifact_registry_repository.backend.name
}
