from distutils.core import setup

setup(name='airflow-secrets-sops',
      version='0.0.6',
      packages=['airflow.sops'],
      package_dir={'': 'src'},
      python_requires='>=3.8',
      install_requires=[
            "apache-airflow==2.2.3",
            "apache-airflow-providers-google==6.2.0",
            "sops==1.18",
            "markupsafe==2.0.1"
      ])
