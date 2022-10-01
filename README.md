## Setup
```shell
source .env/bin/activate
pip install -r requirements.txt
```

## Build
```shell
pip install build
python -m build
```

## Push
To GCP artifact registry
```shell
pip install twine keyrings.google-artifactregistry-auth wheel
python setup.py bdist_wheel
pip config set global.index-url https://_json_key_base64:***gcp_registry_writer_service_account_key***@europe-west1-python.pkg.dev/cm-build/comatch-python/simple/
python -m twine upload --repository-url https://europe-west1-python.pkg.dev/cm-build/comatch-python/ dist/*
```

## SOPS
Encrypt
```shell
export KMS_PATH=$(gcloud kms keys list --location europe-west1 --keyring cm-secrets --project cm-secrets | awk 'FNR == 2 {print $1}')
sops --encrypt --encrypted-regex '^(password|extra)$' --gcp-kms $KMS_PATH here.yaml > here.enc.yaml
```
