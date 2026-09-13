terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # Backend local por defecto (state se ignora vía .gitignore).
  # Para un uso multi-persona/producción, migrar a un backend remoto
  # (S3 + DynamoDB lock table) documentado en docs/REMOTE_STATE.md.
}

provider "aws" {
  region = var.aws_region
}

data "aws_caller_identity" "current" {}

# ---------------------------------------------------------------------------
# NOTA: el frontend de este proyecto se hospeda en GCP (Cloud Storage),
# no en AWS — ver infra/gcp/main.tf. Este módulo AWS solo contiene el
# recurso "gobernado" (IAM) sobre el que actúa el AwsAdapter, más la
# identidad acotada del backend.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Política IAM "diana" — a la que el AwsAdapter asigna/retira usuarios
# en cada onboarding/offboarding. Deliberadamente inofensiva (solo permite
# comprobar la propia identidad), para que la demo sea segura de mostrar
# en vivo sin abrir permisos reales sobre la cuenta.
# ---------------------------------------------------------------------------

resource "aws_iam_policy" "demo_target" {
  name        = "${var.project_name}-demo-viewer"
  description = "Política de ejemplo que cloud-iam-hub asigna a usuarios de demo durante el onboarding/offboarding."

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "HarmlessDemoPermission"
        Effect   = "Allow"
        Action   = ["sts:GetCallerIdentity"]
        Resource = "*"
      }
    ]
  })
}

# ---------------------------------------------------------------------------
# Identidad del backend — usuario IAM dedicado y acotado por path, en vez
# de usar credenciales personales/admin para correr el AwsAdapter.
# ---------------------------------------------------------------------------

resource "aws_iam_user" "backend_operator" {
  name = "${var.project_name}-backend-operator"
  path = var.demo_iam_path
}

resource "aws_iam_access_key" "backend_operator" {
  user = aws_iam_user.backend_operator.name
}

resource "aws_iam_policy" "backend_operator_policy" {
  name        = "${var.project_name}-backend-operator-policy"
  description = "Permisos mínimos para que el AwsAdapter cree/borre usuarios de demo bajo ${var.demo_iam_path} y les asigne la política diana."

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "ManageDemoUsersOnly"
        Effect = "Allow"
        Action = [
          "iam:CreateUser",
          "iam:DeleteUser",
          "iam:GetUser",
          "iam:ListUsers",
          "iam:TagUser",
          "iam:CreateAccessKey",
          "iam:DeleteAccessKey",
          "iam:ListAccessKeys",
          "iam:UpdateAccessKey",
          "iam:AttachUserPolicy",
          "iam:DetachUserPolicy",
          "iam:ListAttachedUserPolicies",
          "iam:PutUserPolicy",
          "iam:DeleteUserPolicy",
          "iam:ListUserPolicies"
        ]
        # El path scoping es lo que impide que este usuario del backend
        # pueda tocar cualquier otro usuario/rol de la cuenta.
        Resource = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:user${var.demo_iam_path}*"
      },
      {
        Sid      = "AttachOnlyDemoTargetPolicy"
        Effect   = "Allow"
        Action   = ["iam:GetPolicy", "iam:GetPolicyVersion"]
        Resource = aws_iam_policy.demo_target.arn
      }
    ]
  })
}

resource "aws_iam_user_policy_attachment" "backend_operator_attach" {
  user       = aws_iam_user.backend_operator.name
  policy_arn = aws_iam_policy.backend_operator_policy.arn
}
