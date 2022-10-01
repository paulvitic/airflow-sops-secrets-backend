from distutils.core import setup

setup(name='airflow-secrets-sops',
      version='0.0.1',
      packages=['airflow.sops'],
      package_dir={'': 'src'},
      python_requires='>=3.8',
      # these are te  transient dependencies that will be installed,
      # when this package is installed
      install_requires=[
            "apache-airflow==2.2.3",
            "apache-airflow-providers-google==6.2.0",
            "sops==1.18",
            "markupsafe==2.0.1"
      ])
