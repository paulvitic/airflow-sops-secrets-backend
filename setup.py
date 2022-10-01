from distutils.core import setup

setup(name='airflow-secrets-sops',
      version='0.0.1',
      packages=['airflow_sops'],
      package_dir={'': 'src'},
      python_requires='>=3.7',
      install_requires=[
          "apache-airflow==2.2.3",
          "google-cloud-storage>=1.43.0",
          "google-cloud-kms>=2.10.1",
          "sops==1.18",
          "markupsafe==2.0.1",
      ])
