import os
import atexit

from typing import TYPE_CHECKING, Dict, Optional
from io import BytesIO
from ruamel.yaml import YAML
from base64 import b64decode
from google.cloud.kms import KeyManagementServiceClient, DecryptRequest
from airflow.exceptions import AirflowException
from airflow.secrets import BaseSecretsBackend
from airflow.utils.log.logging_mixin import LoggingMixin
from google.cloud.storage import Client as StorageClient
from google.auth import default
from google.auth.exceptions import DefaultCredentialsError
from .helpers import _get_key_from_pgp, _check_rotation_needed, _walk_and_decrypt

if TYPE_CHECKING:
    # Avoid circular import problems when instantiating the backend during configuration.
    # See: https://github.com/apache/airflow/pull/25810/files/44399b7a3ccf151afa469367dd9319107138218a
    from airflow.models.connection import Connection

# Composer environment key for bucket name.
BUCKET_NAME = os.environ.get('GCS_BUCKET')

YAML_FILE_EXT = "yaml"


class GcsSopsSecretsBackend(BaseSecretsBackend, LoggingMixin):
    def __init__(
            self,
            project_id: Optional[str] = None,
            bucket_name: str = None,
            connections_prefix: str = "sops/connections",
            variables_prefix: str = "sops/variables",
            encrypted_file_ext: str = "enc",
            ignore_mac: bool = True):
        super().__init__()
        self.project_id = project_id
        self.bucket_name = bucket_name
        self.connections_prefix = connections_prefix
        self.variables_prefix = variables_prefix
        self.encrypted_file_ext = encrypted_file_ext
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

        if not self.encrypted_file_ext:
            self.file_ext = YAML_FILE_EXT
        else:
            self.file_ext = "{}.{}".format(self.encrypted_file_ext, YAML_FILE_EXT)

        self.storage_client = StorageClient(project=self.project_id)
        self.kms_client = KeyManagementServiceClient()

        atexit.register(self._cleanup)

    def get_connection(self, conn_id: str) -> Optional['Connection']:
        stream = self._download_to_stream("{}/{}.{}".format(self.connections_prefix, conn_id, self.file_ext))
        conn_dict = self._decrypt_stream(stream, ignore_mac=self.ignore_mac)
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
        stream = self._download_to_stream("{}/{}.{}".format(self.variables_prefix, key, self.file_ext))
        var_dict = self._decrypt_stream(stream, ignore_mac=self.ignore_mac)
        if var_dict and var_dict.get("value"):
            return var_dict["value"]
        return None

    def _download_to_stream(self, source_blob_name):
        """Downloads a blob to a stream or other file-like object."""
        bucket = self.storage_client.bucket(self.bucket_name)

        blob = bucket.blob(source_blob_name)
        file_obj = BytesIO()
        blob.download_to_file(file_obj)

        file_obj.seek(0)
        return file_obj

    def _decrypt_stream(self, file_obj: BytesIO, ignore_mac: bool) -> Optional[Dict]:
        yaml = YAML(typ='safe', pure=True)
        tree = yaml.load(file_obj)
        key, tree = self._get_key(tree)
        _check_rotation_needed(tree)
        tree = _walk_and_decrypt(tree, key, ignoreMac=ignore_mac)
        if tree:
            tree.pop('sops', None)
            return dict(tree)
        return None

    def _get_key(self, tree):
        """Obtain a 256 bits symetric key.

        If the document contain an encrypted key, try to decrypt it using
        KMS or PGP. Otherwise, generate a new random key.

        """
        key = self._get_key_from_kms(tree)
        if not (key is None):
            return key, tree
        key = _get_key_from_pgp(tree)
        if not (key is None):
            return key, tree

        raise AirflowException("could not retrieve a key to encrypt/decrypt the tree")

    def _get_key_from_kms(self, tree):
        """Get the key form the KMS tree leave."""
        try:
            kms_tree = tree['sops']['gcp_kms']
        except KeyError:
            return None
        i = -1
        errors = []
        for entry in kms_tree:
            if not entry:
                continue
            i += 1
            try:
                enc = entry['enc']
            except KeyError:
                continue
            if 'resource_id' not in entry or entry['resource_id'] == "":
                self.log.warning("WARN: KMS resource id not found skipping entry %s" % i)
                continue

            try:
                request = DecryptRequest(name=entry['resource_id'], ciphertext=b64decode(enc))
                response = self.kms_client.decrypt(request=request)
            except Exception as e:
                errors.append("kms %s failed with error: %s " % (entry['resource_id'], e))
                continue
            return response.plaintext

        self.log.warning("WARN: no KMS client could be accessed:")
        for err in errors:
            self.log.warning("* %s" % err)

        return None

    def _cleanup(self):
        self.log.debug("closing")
        self.storage_client.close()
        self.kms_client.transport.close()
