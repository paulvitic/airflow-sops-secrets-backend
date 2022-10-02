from distutils.core import setup

setup(name='airflow-secrets-sops',
      version='0.0.4',
      packages=['airflow.sops'],
      package_dir={'': 'src'},
      python_requires='>=3.8',
      # these are the transient dependencies that will be installed,
      # when this package is installed
      install_requires=[
            "apache-airflow>=2.2.3",
            "google-cloud-kms>=2.10.1",
            "google-cloud-storage>=1.43.0",
            "ruamel.yaml>=0.17.21",
            "markupsafe==2.0.1"
      ])
