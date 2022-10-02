from os import environ
from typing import TYPE_CHECKING, Optional

from airflow.exceptions import AirflowException
from airflow.secrets import BaseSecretsBackend
from airflow.utils.log.logging_mixin import LoggingMixin

if TYPE_CHECKING:
    # Avoid circular import problems when instantiating the backend during configuration.
    # See: https://github.com/apache/airflow/pull/25810/files/44399b7a3ccf151afa469367dd9319107138218a
    from airflow.models.connection import Connection

from google.auth import default
from google.auth.exceptions import DefaultCredentialsError

from .gcs import _download_to_stream
from .yaml import _decrypt_stream

# Composer environment key for bucket name.
BUCKET_NAME = environ.get('GCS_BUCKET')


class GcsSopsSecretsBackend(BaseSecretsBackend, LoggingMixin):
    def __init__(
            self,
            project_id: Optional[str] = None,
            bucket_name: str = None,
            connections_prefix: str = "airflow-connections",
            variables_prefix: str = "airflow-variables",
            ignore_mac: bool = True):
        super().__init__()
        self.project_id = project_id
        self.bucket_name = bucket_name
        self.connections_prefix = connections_prefix
        self.variables_prefix = variables_prefix
        self.ignore_mac = ignore_mac

        if not self.bucket_name or self.bucket_name == "":
            self.bucket_name = BUCKET_NAME
            if not self.bucket_name or self.bucket_name == "":
                raise AirflowException("Bucket name not found")

        try:
            self.credentials, self.project_id = default()
        except (DefaultCredentialsError, FileNotFoundError):
            self.log.exception(
                'Unable to load credentials for GCP Secret Manager. '
                'Make sure that the keyfile path, dictionary, or GOOGLE_APPLICATION_CREDENTIALS '
                'environment variable is correct and properly configured.'
            )

        # In case project id provided
        if project_id:
            self.project_id = project_id

    def get_connection(self, conn_id: str) -> Optional['Connection']:
        stream = _download_to_stream(self.bucket_name,
                                    '{}/{}.enc.yaml'.format(self.connections_prefix, conn_id),
                                    self.project_id)
        conn_dict = _decrypt_stream(stream, ignore_mac=self.ignore_mac)
        from airflow.models.connection import Connection
        if conn_dict:
            conn = Connection(conn_id=conn_id, **conn_dict)
            return conn
        return None

    def get_conn_uri(self, conn_id: str) -> Optional[str]:
        conn = self.get_connection(conn_id)
        if conn:
            return conn.get_uri()
        return None

    def get_variable(self, key: str) -> Optional[str]:
        stream = _download_to_stream(self.bucket_name,
                                    '{}/{}.enc.yaml'.format(self.variables_prefix, key),
                                    self.project_id)
        var_dict = _decrypt_stream(stream, ignore_mac=self.ignore_mac)
        if var_dict and var_dict.get("value"):
            return var_dict["value"]
        return None
