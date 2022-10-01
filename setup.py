from distutils.core import setup

setup(name='airflow-secrets-sops',
      version='0.0.2',
      packages=['airflow.sops'],
      package_dir={'': 'src'},
      python_requires='>=3.8',
      install_requires=[
          "apache-airflow==2.2.3",
          "google-cloud-storage>=1.43.0",
          "google-cloud-kms>=2.10.1",
          "sops==1.18",
          "markupsafe==2.0.1",
      ])
