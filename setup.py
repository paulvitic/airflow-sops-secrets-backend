from setuptools import setup, find_packages

from gcs_sops_secrets_backend import __version__

setup(
    name='airflow-gcs-sops-secrets-backend',
    version=__version__,
    packages=find_packages(where="./gcs_sops_secrets_backend"),
    url='',
    license='MIT',
    author='Paul Vitic',
    scripts=['test.py'],
    include_package_data=True,
    author_email='p.vitic@comatch.com',
    description='An Airflow custom secrets backend for sops encrypted resources in gcs bucket',
    install_requires=[
        "apache-airflow==2.2.3",
        "google-cloud-storage==1.43.0",
        "google-cloud-kms==2.10.1",
        "sops==1.18",
        "markupsafe==2.0.1",
    ]
)
