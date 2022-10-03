# Airflow SOPS Secrets Backend for GCP KMS
This packages enables Airflow to pull connections and variables
from files in GCP bucket that are encrypted by SOPS using GCP
KMS.

## GCP Config
```terraform
locals {
  gcp_project_id = "your-project-id"
  service_account_name = "your-composer-service-account-name"
}
resource "google_service_account" "composer" {
  account_id   = local.service_account_name
  display_name = local.service_account_name
  project      = local.gcp_project_id
}

resource "google_project_iam_member" "composer_worker" {
  project = local.gcp_project_id
  role   = "roles/composer.worker"
  member = "serviceAccount:${google_service_account.composer.email}"
}

resource "google_kms_key_ring" "secrets" {
  name     = local.gcp_project_id
  location = "europe-west1"
  project  = local.gcp_project_id
}

resource "google_kms_crypto_key" "secrets_sops" {
  name            = "secrets_sops"
  key_ring        = google_kms_key_ring.secrets.id
  rotation_period = "7776000s" // 90 days
}

resource "google_kms_crypto_key_iam_member" "composer_sops_decrypter" {
  crypto_key_id = google_kms_crypto_key.secrets_sops.id
  role          = "roles/cloudkms.cryptoKeyDecrypter"
  member        = "serviceAccount:${google_service_account.composer.email}"
}

# some mandatory attributes omitted
resource "google_composer_environment" "composer" {
  name     = "your-composer-environment-name"
  region   = "europe-west1"
  project  = local.gcp_project_id
  config {
    software_config {
      airflow_config_overrides = {
        secrets-backend                          = "airflow_sops.secrets_backend.GcsSopsSecretsBackend"
      }
      pypi_packages = {
        airflow-secrets-sops                   = "==0.0.1"
      }
    }
    node_config {
      service_account = google_service_account.composer.email
    }
  }
}
```

## Setup
```shell
source .env/bin/activate
pip config set --site global.extra-index-url https://pypi.org/simple
pip install -r requirements.txt
```

## Test
```shell
pip install . airflow-sops-secrets-backend[test] pytest
pytest
```
or 
```shell
pip install . airflow-sops-secrets-backend[test] 
python -m unittest tests/test_integration.py
```

## Build & Push
```shell
pip install airflow-sops-secrets-backend[dev]
python -m build
```
this builds the project then to push (to private GCP artifact registry)
```shell
python setup.py bdist_wheel
pip config set --site global.index-url https://_json_key_base64:***gcp_registry_writer_service_account_key***@europe-west1-python.pkg.dev/cm-build/comatch-python/simple/
python -m twine upload --repository-url https://europe-west1-python.pkg.dev/cm-build/comatch-python/ dist/*
```

## SOPS
Encrypt files and upload to GCP bucket sops/connections directory
```shell
export KMS_PATH=$(gcloud kms keys list --location europe-west1 --keyring cm-secrets --project cm-secrets | awk 'FNR == 2 {print $1}')
sops --encrypt --encrypted-regex '^(password|extra)$' --gcp-kms $KMS_PATH some-connection.yaml > some-connection.enc.yaml
```
