# cloud-iam-hub

**One Cloud to Rule Them All** — un cerebro serverless en GCP que gobierna
identidades en AWS, GCP y Azure con el patrón Adapter.

Construido para la charla *"3 nubes, 1 cerebro: cómo goberné AWS y Azure
desde GCP"* en DevFest Quito 2026. Se comparte como regalo del talk: toma
este repo, mejóralo, rómpelo, aprende de él.

## Por qué existe esto

Cada nube resuelve IAM de forma incompatible. Un rol de AWS no tiene
equivalente directo en el RBAC de Azure ni en las service accounts de
GCP. Gestionar identidades en una sola nube ya es trabajo; hacerlo en
tres a mano es una fuente garantizada de *policy drift* y brechas de
auditoría.

`cloud-iam-hub` no reemplaza herramientas de mercado como CIEM (Wiz,
Prisma Cloud, Microsoft Defender for Cloud) o IGA (SailPoint). Esas
plataformas auditan y recortan permisos excesivos across-cloud. Este
proyecto ataca un problema distinto y complementario: **el lifecycle**
—crear acceso y revocarlo, en las 3 nubes, con una sola llamada, con
trazabilidad unificada— usando una abstracción propia y entendible.

## Arquitectura

El control plane vive en GCP. Desde ahí se orquesta AWS y Azure.

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

Ver el diagrama completo en [`diagrams/cloud-iam-hub.drawio`](diagrams/cloud-iam-hub.drawio)
(ábrelo en [draw.io](https://app.diagrams.net)) y la versión navegable en
[`arquitectura-cloud-iam-hub.html`](arquitectura-cloud-iam-hub.html).

**Nota de diseño:** el diagrama original contempla Eventarc + Cloud Run
Workers para desacoplar la escritura en Firestore de la ejecución del
fan-out. La versión actual del código simplifica esa pieza: la propia
API dispara el fan-out con `asyncio.gather` en el mismo request. Migrar a
Eventarc real es el primer "next step" natural para quien continúe este
proyecto (ver [Roadmap](#roadmap)).

## El patrón Adapter, en código

Todo adapter implementa la misma interfaz (`app/adapters/base.py`):

```python
class CloudAdapter(ABC):
    async def onboard(self, *, identity_id, display_name, role_key) -> AdapterResult: ...
    async def offboard(self, *, identity_id, provider_ref) -> AdapterResult: ...
```

El orquestador (`IdentityService`) solo conoce esta interfaz. No sabe —ni
le importa— si por debajo hay boto3, el SDK de Google o Microsoft Graph.

## Sí se puede — pero no como esperas

Cada nube tiene un comportamiento que rompe la intuición del primer
intento. En los tres casos **la operación sí es posible**, pero la API no
da un camino directo:

| Nube | Lo que uno intentaría primero | Por qué no funciona así | El camino real |
|---|---|---|---|
| **GCP** | `setIamPolicy()` con solo el binding nuevo | Reemplaza **toda** la política del recurso, no la mezcla | `getIamPolicy()` → mutar bindings en memoria → `setIamPolicy()` con el `etag` obtenido, reintentando si la API responde `409 ABORTED` |
| **AWS** | Buscar una API `DisableUser` | No existe — IAM no tiene un "disable" nativo por usuario | Compone varios pasos: desactivar/eliminar access keys, eliminar el login profile, desasociar policies/grupos (o adjuntar `AWSDenyAll`). Con IAM Identity Center (SSO) sí hay un disable directo en el store de identidades |
| **Azure** | Un solo `assign()` que cree usuario y le dé permisos | Identidad y permisos viven en **dos planos separados** con dos SDKs distintos | **Entra ID** (Microsoft Graph) para la identidad y `accountEnabled`, **Azure RBAC** (`azure-mgmt-authorization`) para los `roleAssignments` sobre un scope (subscription/RG/recurso) |

Implementación real de cada caso: [`aws_adapter.py`](backend/app/adapters/aws_adapter.py),
[`gcp_adapter.py`](backend/app/adapters/gcp_adapter.py),
[`azure_adapter.py`](backend/app/adapters/azure_adapter.py).

## Estructura del repo

```
cloud-iam-hub/
├── infra/
│   ├── aws/      # Terraform: policy IAM "diana" + usuario del backend (path-scoped)
│   ├── gcp/      # Terraform: Firestore, Cloud Run, Secret Manager, Artifact Registry, bucket frontend
│   └── azure/    # Terraform: resource group, app registration, RBAC scope
├── backend/
│   ├── Dockerfile         # Imagen para Cloud Run
│   └── app/
│       ├── models/         # Contrato unificado (Identity, Role, Assignment, Audit)
│       ├── adapters/       # CloudAdapter + AwsAdapter/GcpAdapter/AzureAdapter/MockAdapter
│       ├── services/       # IdentityService (orquestador) + adapter_factory
│       ├── repositories/   # Firestore real + InMemory (sandbox)
│       └── routers/        # POST /onboard, POST /offboard, GET /audit (protegidos con X-Api-Key)
├── frontend/       # HTML/JS estático, servido desde Cloud Storage (GCP)
└── diagrams/       # cloud-iam-hub.drawio
```

## Correr en local (modo sandbox — sin credenciales de ninguna nube)

El modo por defecto es `sandbox`: todos los adapters son simulados
(`MockAdapter`) y el estado vive en memoria (`InMemoryRepository`). Es el
plan B en tarima, pero también la forma más rápida de explorar el repo.

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8080
```

En otra terminal, sirve el frontend:

```bash
cd frontend
python3 -m http.server 9000
```

Abre `http://localhost:9000`, pon `http://localhost:8080` como URL del
backend, y dispara un onboarding. Verás el fan-out a las 3 nubes y el
audit trail, todo simulado.

## Correr en modo `live` (llamadas reales a AWS + GCP + Azure)

⚠️ **Antes de activar `live`, lee la sección de seguridad más abajo.**

### Opción A — local, apuntando a las nubes reales

1. Provisiona la infraestructura de cada nube con Terraform:

```bash
cd infra/aws    && terraform init && terraform apply
cd ../gcp       && terraform init && terraform apply
cd ../azure     && terraform init && terraform apply
```

2. Copia `backend/.env.example` a `backend/.env` y completa los valores
   con los outputs de Terraform (`terraform output`), incluyendo
   `API_SHARED_SECRET` (generarlo con `openssl rand -hex 24`).

3. Corre el backend con `CLOUD_IAM_MODE=live`.

4. Sube el frontend al bucket generado por Terraform:

```bash
cd frontend
./deploy.sh $(terraform -chdir=../infra/gcp output -raw frontend_bucket_name)
```

### Opción B — todo desplegado en GCP (Cloud Run + Cloud Storage)

`infra/gcp` ya provisiona un servicio Cloud Run para el backend, un
secreto en Secret Manager con `API_SHARED_SECRET` generado
automáticamente, y el bucket del frontend. El primer `apply` usa una
imagen placeholder; el flujo completo es:

```bash
cd infra/gcp
terraform init && terraform apply

# Construir y publicar la imagen real del backend (usa Cloud Build, sin Docker local):
cd ../../backend
gcloud builds submit . \
  --tag "$(terraform -chdir=../infra/gcp output -raw artifact_registry_repo | sed 's#.*#&#')/backend:latest"
# (o construye el tag manualmente: <region>-docker.pkg.dev/<project>/cloud-iam-hub/backend:latest)

gcloud run deploy cloud-iam-hub-backend \
  --image <la-imagen-de-arriba> \
  --region <tu-region>

# Ver la URL pública del backend y el secret generado:
cd ../infra/gcp
terraform output backend_url
terraform output -raw api_shared_secret

# Subir el frontend:
cd ../../frontend
./deploy.sh $(terraform -chdir=../infra/gcp output -raw frontend_bucket_name)
```

Abre la URL del frontend, pega la URL del backend y el `api_shared_secret`
en los campos correspondientes, y dispara el onboarding.

## Seguridad — importante antes de correr en modo `live`

Este proyecto se comparte como **repo público**. Si lo vas a correr con
credenciales reales, ten en cuenta:

- **Usa cuentas/tenants de prueba, nunca de producción ni corporativos.**
  El código está diseñado así: el usuario IAM de AWS está acotado por
  `path` (`/cloud-iam-hub-demo/`), el service account de GCP tiene
  permisos mínimos sobre un proyecto de prueba, y el RBAC de Azure está
  limitado a un resource group vacío.
- **Chequeo de tenant Azure.** `app/config.py` expone
  `assert_azure_tenant_is_safe()`: en modo `live`, si el tenant activo no
  coincide exactamente con `AZURE_TENANT_ID`, el adapter se niega a
  ejecutar cualquier operación. Esto evita que una sesión de `az login`
  distinta (por ejemplo, un tenant corporativo) sea tocada por accidente.
- **El permiso de Graph de Azure es todo-el-tenant, mitigado en código.**
  `User.ReadWrite.All` no se puede acotar de forma nativa a un
  subconjunto de usuarios en Microsoft Graph. Como mitigación,
  `AzureAdapter` se niega a operar sobre cualquier UPN que no siga
  exactamente el patrón `demo-<identity_id>@<tenant>`
  (`_assert_is_demo_principal`), y el secreto del service principal
  expira a los 7 días (`infra/azure/main.tf`).
- **La API no debe quedar abierta al público.** El frontend estático y
  Cloud Run son públicos por diseño (para que cualquiera pueda ver la
  demo en un navegador), pero `POST /onboard`, `POST /offboard` y
  `GET /audit` exigen el header `X-Api-Key` si `API_SHARED_SECRET` está
  configurado (`app/routers/identity.py -> require_api_key`). El módulo
  `infra/gcp` genera este secreto automáticamente vía Secret Manager —
  **defínelo siempre** antes de desplegar a un entorno accesible
  públicamente. Compártelo solo con quien deba disparar la demo.
- **Nunca commitees `.env`, `terraform.tfvars`, `*.tfstate` ni archivos de
  credenciales.** El `.gitignore` de este repo ya los excluye.
- **Los recursos "gobernados" son deliberadamente inofensivos.** La
  policy de AWS solo permite `sts:GetCallerIdentity`; el rol de Azure es
  `Reader` sobre un resource group vacío; el binding de GCP es sobre un
  service account de demo. Ningún onboarding/offboarding de este proyecto
  otorga permisos peligrosos.

## Dónde encaja esto frente al mercado

Existe una categoría de mercado real para "IAM multicloud": **CIEM**
(Wiz, Prisma Cloud, Defender for Cloud, Tenable, Sonrai) e **IGA**
(SailPoint, Saviynt). Esas plataformas se enfocan en **auditar y
recortar** permisos excesivos (postura de seguridad, mayormente
read-only). `cloud-iam-hub` se enfoca en **aprovisionar y orquestar** el
ciclo de vida (onboarding/offboarding activo, con escritura real en las
3 nubes) — un problema relacionado pero distinto, resuelto aquí con una
abstracción propia y open source en vez de una plataforma comercial.

## Roadmap (ideas para quien continúe este repo)

- **Reemplazar el fan-out `asyncio.gather` por Eventarc + Cloud Run
  Workers reales** (el diagrama original ya contempla esta pieza). Es el
  cambio más grande pendiente: implica separar `onboard`/`offboard` en
  "escribir intención" vs. "aplicar cambio" (con estado `pending` visible
  mientras el Worker procesa), un servicio Cloud Run nuevo que reciba
  CloudEvents desde un trigger de Eventarc sobre Firestore, y los permisos
  IAM del *service agent* de Eventarc (`roles/eventarc.eventReceiver`,
  `roles/run.invoker`). No tiene buen emulador local, así que cada
  iteración de prueba requiere desplegar de verdad.
- Agregar más roles unificados además de `viewer`/`editor`.
- Sustituir el usuario de demo de AWS por un rol federado (IAM Identity
  Center) para mostrar el camino de "disable" nativo vía SSO.
- Tests automatizados con `pytest` sobre `IdentityService` usando
  `InMemoryRepository` + `MockAdapter` (ya desacoplados para esto).

## Licencia

MIT. Úsalo, rómpelo, mejóralo.
