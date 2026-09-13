variable "aws_region" {
  description = "Región de AWS donde se despliega el bucket del frontend y los recursos IAM."
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Prefijo usado para nombrar todos los recursos del proyecto."
  type        = string
  default     = "cloud-iam-hub"
}

variable "demo_iam_path" {
  description = <<-EOT
    Path de IAM bajo el cual el backend crea/borra usuarios de demo (onboarding/offboarding).
    Acotar todos los permisos a este path es lo que evita que el backend pueda tocar
    cualquier otro usuario/rol de la cuenta.
  EOT
  type        = string
  default     = "/cloud-iam-hub-demo/"
}


