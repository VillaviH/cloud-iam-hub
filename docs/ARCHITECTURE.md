# Arquitectura de cloud-iam-hub

## Visión general

El control plane vive en **GCP**. Desde ahí se orquesta el ciclo de vida
de identidades (onboarding/offboarding) en **AWS** y **Azure**, además
del propio GCP.

```
Admin/CLI ──▶ Cloud Run API (FastAPI) ──▶ Firestore (Identity·Role·Assignment·Audit)
                                              │
                                     fan-out asyncio.gather
                                              │
                    ┌─────────────────────────┼─────────────────────────┐
                    ▼                         ▼                         ▼
              AwsAdapter                GcpAdapter                AzureAdapter
              (boto3)          (resourcemanager_v3 + etag)   (Graph + azure-mgmt-authorization)
                    │                         │                         │
                    ▼                         ▼                         ▼
            IAM users/policies      IAM policy del proyecto      Entra ID + Azure RBAC
```

Diagrama visual completo: [`diagrams/cloud-iam-hub.drawio`](../diagrams/cloud-iam-hub.drawio)
(abrir en [draw.io](https://app.diagrams.net)) y versión navegable en
[`arquitectura-cloud-iam-hub.html`](../arquitectura-cloud-iam-hub.html).

## Componentes

### Cloud Run · API (FastAPI)

Expone tres endpoints (`app/routers/identity.py`):

- `POST /onboard` — crea una `Identity`, un `Assignment` por proveedor
  solicitado, y dispara el fan-out.
- `POST /offboard` — revoca los `Assignment` existentes de una `Identity`
  en los proveedores indicados (o en todos).
- `GET /audit` — consulta el `AuditEntry` trail, por `correlation_id` o
  los más recientes.

### Firestore — estado del hub

Tres colecciones append-friendly:

- `identities` — un documento por `Identity`.
- `assignments` — un documento por `Assignment` (identity × provider).
- `audit` — append-only, nunca se edita ni se borra un registro.

### IdentityService — el orquestador

`app/services/identity_service.py` es el corazón narrativo del proyecto:

1. Escribe la **intención** (`Identity` + `Assignment`s) en el
   repositorio antes de tocar ninguna nube.
2. Dispara el **fan-out** — todos los `Assignment`s de una operación se
   procesan en paralelo con `asyncio.gather`, uno por `CloudAdapter`.
3. Cada resultado (éxito o error) actualiza el `Assignment` y agrega una
   `AuditEntry`, todas compartiendo el mismo `correlation_id` para poder
   reconstruir la operación cross-cloud completa con una sola consulta.

**Nota de simplificación deliberada:** el diagrama original contempla
Eventarc + Cloud Run Workers para desacoplar la escritura en Firestore
de la ejecución del fan-out (arquitectura más resiliente y escalable).
La versión actual del código hace el fan-out directamente desde la API
en el mismo request — misma historia arquitectónica, con menos piezas de
infraestructura que puedan fallar antes de una demo en vivo. Migrar a
Eventarc real es el primer paso natural del [roadmap](../README.md#roadmap).

### CloudAdapter — el patrón central

`app/adapters/base.py` define el contrato que implementan `AwsAdapter`,
`GcpAdapter`, `AzureAdapter` y `MockAdapter`:

```python
class CloudAdapter(ABC):
    async def onboard(self, *, identity_id, display_name, role_key) -> AdapterResult: ...
    async def offboard(self, *, identity_id, provider_ref) -> AdapterResult: ...
```

El `IdentityService` solo conoce esta interfaz. Los detalles reales de
cada nube (ver [`docs/IAM_CLOUD_MAPPING.md`](IAM_CLOUD_MAPPING.md)) están
completamente encapsulados dentro de cada implementación.

### Modo sandbox — plan B en tarima

`app/services/adapter_factory.py` decide, según `CLOUD_IAM_MODE`, si
entrega los adapters reales o el `MockAdapter` (simulado, sin llamadas de
red). En sandbox, además, el repositorio es `InMemoryRepository` en vez
de Firestore. El resto del sistema (`IdentityService`, routers) no sabe
en qué modo está corriendo — habla siempre contra las mismas interfaces
(`CloudAdapter`, `IdentityRepository`).

Esto significa que si la red o las credenciales fallan justo antes de
salir a tarima, cambiar `CLOUD_IAM_MODE=live` a `CLOUD_IAM_MODE=sandbox`
(una sola variable de entorno) deja la demo funcionando end-to-end sin
ninguna dependencia externa.

## Frontend

Un HTML/JS estático (sin build step, sin framework) servido desde un
bucket de **Cloud Storage** con hosting de sitio web — coherente con que
el proyecto se presenta en un evento de GCP. Consume la API vía `fetch`
directo a la URL configurada por el usuario en la propia página (no hay
backend-for-frontend ni proxy).

## Seguridad del diseño

- **Path/scope siempre acotado.** El usuario IAM de AWS que usa el
  backend solo puede operar sobre usuarios bajo `/cloud-iam-hub-demo/`;
  el service account de GCP tiene permisos sobre un proyecto de prueba;
  el RBAC de Azure está limitado a un resource group vacío creado solo
  para la demo.
- **Verificación de tenant en runtime.** `assert_azure_tenant_is_safe()`
  compara el tenant activo contra `AZURE_TENANT_ID` antes de cualquier
  llamada real a Azure, y falla explícitamente si no coincide.
- **Recursos "gobernados" deliberadamente inofensivos** — ver detalle en
  el README, sección de seguridad.
