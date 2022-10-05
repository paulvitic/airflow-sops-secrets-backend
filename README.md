# Airflow SOPS Secrets Backend for GCP KMS
This packages enables Airflow to pull connections and variables
from files in GCP bucket that are encrypted by [SOPS](https://github.com/mozilla/sops) 
using GCP KMS.

## Configure Airflow
Add following to *airflow.cfg*.
```text
[secrets]
backend = airflow_sops.secrets_backend.GcsSopsSecretsBackend
backend_kwargs = {"project_id": "your-project-id"}
```
Available parameters to backend_kwargs:
* project_id: Optional. GCP project id where the GCS bucket which holds the encrypted connections/variables files reside., 
* bucket_name: Optional. If not submitted tries retrieving from Composer GCS_BUCKET environment variable 
* connections_prefix. Optional. Default is "sops/connections". The folder in GCS bucket that holds encrypted connections.
* variables_prefix: Optional. Default is "sops/variables". The folder in GCS bucket that holds encrypted variables., 
* encrypted_file_ext: Optional. Default is "enc". The file extension for encrypted sops files. The format is <connection_id or variable_key>.<encrypted_file_ext>.yaml
* ignore_mac: Optional. Default is True. Ignores file checksum when true.

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

## SOPS
Install [SOPS](https://github.com/mozilla/sops). Encrypt files
using GCP KMS and upload to GCP bucket sops/connections directory
```shell
export KMS_PATH=$(gcloud kms keys list --location europe-west1 --keyring your-keyring --project your-gcp-project | awk 'FNR == 2 {print $1}')
sops --encrypt --encrypted-regex '^(password|extra)$' --gcp-kms $KMS_PATH some-connection.yaml > some-connection.enc.yaml
```

## Setup
```shell
python -m venv .venv
source .venv/bin/activate
pip config set --site global.extra-index-url https://pypi.org/simple
pip install -r requirements.txt
```

## Test
```shell
pip install . airflow-sops-secrets-backend[test]
pytest
```

## Build
```shell
pip install airflow-sops-secrets-backend[dev]
python -m build
```
