terraform {
  required_version = ">= 1.5.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.100"
    }
    azuread = {
      source  = "hashicorp/azuread"
      version = "~> 2.53"
    }
  }

  # Backend local por defecto (state se ignora vía .gitignore).
}

provider "azurerm" {
  features {}
}

provider "azuread" {}

data "azurerm_client_config" "current" {}

# ---------------------------------------------------------------------------
# ADVERTENCIA DE SEGURIDAD
# Este módulo asume que el usuario/CLI está autenticado contra un tenant
# de Azure PROPIO (personal o de pruebas), nunca uno corporativo. El
# backend (AzureAdapter) valida esto también en tiempo de ejecución
# (ver backend/app/config.py) comparando el tenant_id activo contra
# AZURE_TENANT_ID esperado. No se referencia ningún tenant/organización
# real en este repositorio.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Resource Group — scope sobre el que se hacen las roleAssignments (RBAC)
# de demo. Deliberadamente vacío y aislado: no contiene ningún recurso
# de producción.
# ---------------------------------------------------------------------------

resource "azurerm_resource_group" "demo" {
  name     = var.resource_group_name
  location = var.location

  tags = {
    project = var.project_name
    purpose = "cloud-iam-hub-demo"
  }
}

# ---------------------------------------------------------------------------
# App Registration + Service Principal — identidad que usa el backend
# (AzureAdapter) para hablar con Microsoft Graph (Entra ID) y con
# Azure RBAC. Nunca usar tu cuenta personal directamente desde el backend.
# ---------------------------------------------------------------------------

resource "azuread_application" "backend" {
  display_name = "${var.project_name}-backend"
}

resource "azuread_service_principal" "backend" {
  client_id = azuread_application.backend.client_id
}

resource "azuread_service_principal_password" "backend" {
  service_principal_id = azuread_service_principal.backend.id
}

# Rol RBAC (plano de autorización) — acotado únicamente al resource group
# de demo, jamás a la subscription completa.
resource "azurerm_role_assignment" "backend_rbac_scope" {
  scope                = azurerm_resource_group.demo.id
  role_definition_name = "Reader"
  principal_id         = azuread_service_principal.backend.object_id
}

# Permiso de Microsoft Graph (plano de identidad) para que el backend
# pueda crear/deshabilitar usuarios de demo. Requiere consentimiento de
# administrador del tenant (tu propio tenant personal).
resource "azuread_application_api_access" "backend_graph" {
  application_id = azuread_application.backend.id
  api_client_id  = "00000003-0000-0000-c000-000000000000" # Microsoft Graph

  role_ids = [
    "741f803b-c850-494e-b5df-cde7c675a1ca", # User.ReadWrite.All (app role)
  ]
}

# NOTA: este permiso de aplicación requiere consentimiento de administrador
# del tenant. En un tenant personal, tu propio usuario ya es Global Admin,
# así que basta con ejecutar tras el apply:
#   az ad app permission admin-consent --id <backend_client_id>

# ---------------------------------------------------------------------------
# Rol RBAC "diana" adicional — un segundo rol de solo lectura que el
# AzureAdapter asigna/retira a los USUARIOS de demo (no al backend) en
# cada onboarding/offboarding.
# ---------------------------------------------------------------------------

# El rol RBAC de la demo es el built-in "Reader" ya usado arriba como
# ejemplo de scope; se reutiliza su nombre en las asignaciones que el
# AzureAdapter crea dinámicamente en tiempo de ejecución (ver
# backend/app/adapters/azure_adapter.py), no aquí en Terraform, porque
# esas asignaciones son efímeras (una por cada onboarding de demo).
