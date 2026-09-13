variable "location" {
  description = "Región de Azure donde se crea el resource group de demo."
  type        = string
  default     = "eastus"
}

variable "project_name" {
  description = "Prefijo usado para nombrar recursos del proyecto."
  type        = string
  default     = "cloud-iam-hub"
}

variable "resource_group_name" {
  description = "Nombre del resource group que actúa como scope de las asignaciones RBAC de demo."
  type        = string
  default     = "rg-cloud-iam-hub-demo"
}
