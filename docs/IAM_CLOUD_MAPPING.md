# Mapeo de IAM entre AWS, GCP y Azure

Este documento detalla las diferencias reales entre los modelos de IAM
de las tres nubes que gobierna `cloud-iam-hub`, y cómo cada `Adapter`
absorbe esas diferencias detrás del contrato unificado
(`app/models/unified.py`).

## Modelo de abstracción unificado

El hub no modela "usuarios", "roles" y "políticas" con la semántica de
ninguna nube en particular. Modela cuatro conceptos neutrales:

| Concepto unificado | Qué representa |
|---|---|
| `Identity` | Un principal de demo, gobernado en 0 o más nubes |
| `Role` | Un permiso conceptual (`viewer`, `editor`) que cada Adapter traduce |
| `Assignment` | La intención: "esta Identity debe tener este Role en este Provider" |
| `AuditEntry` | Un evento append-only: qué Adapter hizo qué, cuándo, con qué resultado |

Cada `Adapter` traduce estos cuatro conceptos al lenguaje nativo de su
nube. Esa traducción es exactamente donde aparecen las diferencias reales
descritas abajo.

## AWS IAM

- **Modelo:** usuarios, grupos, roles y policies (documentos JSON) que se
  adjuntan (`attach`) a un principal.
- **Identidad:** un `IAM User` con un ARN fijo.
- **Autorización:** policies administradas o inline, adjuntadas al user.
- **Particularidad clave — no existe "disable user":**
  IAM no tiene una API que deshabilite a un usuario de un golpe. El
  offboarding real es una composición de pasos independientes:
  1. Desasociar (`detach_user_policy`) todas las policies administradas.
  2. Eliminar (`delete_user_policy`) las policies inline.
  3. Eliminar (`delete_access_key`) todas las access keys — no se pueden
     "deshabilitar" de forma permanente sin borrarlas si el objetivo es
     revocar acceso por completo (sí existe `update_access_key` para
     marcarlas `Inactive`, pero eso es una revocación parcial/temporal).
  4. Eliminar (`delete_login_profile`) el acceso a la consola, si existe.
  5. Solo entonces se puede eliminar (`delete_user`) el usuario.
- **Excepción:** con **IAM Identity Center (SSO)**, sí existe un disable
  directo a nivel del store de identidades — pero es otro servicio, con
  otra API, fuera del alcance de este adapter.
- **Implementación:** [`backend/app/adapters/aws_adapter.py`](../backend/app/adapters/aws_adapter.py)

## GCP IAM

- **Modelo:** una única `Policy` (documento con `bindings`) por recurso
  (proyecto, folder, organización, o recurso individual).
- **Identidad:** cuentas de usuario, service accounts, o grupos —
  identificados como `member` dentro de un `binding`.
- **Autorización:** cada `binding` asocia un `role` (ej. `roles/viewer`)
  con una lista de `members`.
- **Particularidad clave — `setIamPolicy()` reemplaza TODO:**
  A diferencia de AWS (donde `attach_user_policy` es aditivo),
  `setIamPolicy()` en GCP **sobreescribe la policy completa** del
  recurso. Si se llama con solo el binding nuevo, se borran todos los
  demás bindings existentes.
  El patrón correcto es:
  1. `getIamPolicy()` → trae la policy completa + su `etag`.
  2. Mutar los `bindings` en memoria (agregar o quitar el member).
  3. `setIamPolicy()` enviando la policy completa junto con el `etag`
     obtenido.
  4. Si la API responde `409 ABORTED` (alguien más escribió la policy
     entre el get y el set), reintentar el ciclo completo desde el paso 1.
  El `etag` es un mecanismo de *optimistic locking*: garantiza que no se
  sobreescriban cambios concurrentes de otro proceso.
- **Implementación:** [`backend/app/adapters/gcp_adapter.py`](../backend/app/adapters/gcp_adapter.py)

## Azure (Entra ID + RBAC)

- **Modelo:** dos sistemas separados con dos SDKs distintos.
  - **Entra ID** (antes Azure AD): el directorio de identidades. Se
    gestiona vía **Microsoft Graph**.
  - **Azure RBAC**: el sistema de autorización sobre recursos. Se
    gestiona vía **Azure Resource Manager** (`azure-mgmt-authorization`).
- **Identidad:** un objeto `User` en Entra ID, con la propiedad
  `accountEnabled` (booleana).
- **Autorización:** un `roleAssignment` que vincula un `principalId`
  (el objeto de Entra ID) con una `roleDefinitionId` (ej. `Reader`) sobre
  un `scope` (subscription, resource group, o recurso).
- **Particularidad clave — no hay un solo `assign()`:**
  Crear un usuario funcional con permisos requiere **dos llamadas a dos
  APIs distintas**:
  1. `POST /users` en Microsoft Graph → crea la identidad.
  2. `role_assignments.create()` en Azure RBAC → le otorga permisos sobre
     un scope.
  Si solo se hace el paso 1, el usuario existe pero no puede hacer nada.
  Si solo se hace el paso 2 (imposible sin un `principalId` válido), no
  hay identidad a la que asignarle el rol.
  El **offboarding** también requiere ambos planos: quitar el
  `roleAssignment` (RBAC) y además poner `accountEnabled=false` en Entra
  ID — quitar solo el rol deja al usuario existente pero sin acceso a
  ese recurso puntual; el usuario en sí sigue activo en el directorio.
- **Implementación:** [`backend/app/adapters/azure_adapter.py`](../backend/app/adapters/azure_adapter.py)

## Resumen comparativo

| | AWS | GCP | Azure |
|---|---|---|---|
| ¿Un solo sistema de identidad+permisos? | Sí (IAM) | Sí (IAM policy) | No (Entra ID + RBAC separados) |
| ¿La autorización es aditiva o reemplaza todo? | Aditiva (`attach`/`detach`) | Reemplaza todo (`setIamPolicy`) | Aditiva (`roleAssignment` es su propio objeto) |
| ¿Existe un "disable" directo? | No (requiere composición de pasos) | N/A (se quita el binding) | Sí (`accountEnabled=false`) |
| Mecanismo de concurrencia segura | N/A (operaciones atómicas por policy) | `etag` obligatorio | N/A (cada roleAssignment es un recurso propio) |
