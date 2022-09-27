## Build

```shell
python -m build -n
```

## Push
```shell
pip install twine keyrings.google-artifactregistry-auth wheel
python setup.py bdist_wheel
gcloud auth application-default login
```
