output "resource_group_name" {
  description = "Resource group usado como scope de las asignaciones RBAC de demo."
  value       = azurerm_resource_group.demo.name
}

output "resource_group_id" {
  description = "ID completo del resource group (scope para roleAssignments)."
  value       = azurerm_resource_group.demo.id
}

output "backend_client_id" {
  description = "Client ID (application ID) del service principal del backend."
  value       = azuread_application.backend.client_id
}

output "backend_client_secret" {
  description = "Client secret del service principal del backend. Copiar a backend/.env y NUNCA commitear."
  value       = azuread_service_principal_password.backend.value
  sensitive   = true
}

output "backend_object_id" {
  description = "Object ID del service principal del backend."
  value       = azuread_service_principal.backend.object_id
}

output "tenant_id" {
  description = "Tenant ID activo. Verificar SIEMPRE que sea tu tenant personal, nunca uno corporativo."
  value       = data.azurerm_client_config.current.tenant_id
}
