output "demo_target_policy_arn" {
  description = "ARN de la política que el AwsAdapter asigna/retira en cada onboarding/offboarding."
  value       = aws_iam_policy.demo_target.arn
}

output "backend_operator_user_name" {
  description = "Usuario IAM dedicado que debe usar el backend (no usar credenciales personales)."
  value       = aws_iam_user.backend_operator.name
}

output "backend_operator_access_key_id" {
  description = "Access Key ID del usuario del backend."
  value       = aws_iam_access_key.backend_operator.id
}

output "backend_operator_secret_access_key" {
  description = "Secret Access Key del usuario del backend. Copiar a backend/.env y NUNCA commitear."
  value       = aws_iam_access_key.backend_operator.secret
  sensitive   = true
}

output "demo_iam_path" {
  description = "Path de IAM bajo el cual se crean los usuarios de demo."
  value       = var.demo_iam_path
}
