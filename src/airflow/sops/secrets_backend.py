import atexit
import io
import logging
import sops

from os import environ
from typing import Optional, List, Dict

from google.cloud import storage
from google.cloud.kms import KeyManagementServiceClient, DecryptRequest

from airflow.exceptions import AirflowException
from airflow.providers.google.cloud.secrets.secret_manager import CloudSecretManagerBackend
from airflow.models.connection import Connection

from ruamel.yaml import YAML

log = logging.getLogger(__name__)

# Composer environment key for bucket name.
BUCKET_NAME = environ.get('GCS_BUCKET')


class GcsSopsSecretsBackend(CloudSecretManagerBackend):
    def __init__(
            self,
            connections_prefix: str = "airflow-connections",
            variables_prefix: str = "airflow-variables",
            config_prefix: str = "airflow-config",
            gcp_keyfile_dict: Optional[dict] = None,
            gcp_key_path: Optional[str] = None,
            gcp_scopes: Optional[str] = None,
            project_id: Optional[str] = None,
            sep: str = "-",
            bucket_name: str = None,
            ignore_mac: bool = True,
            **kwargs
    ) -> None:
        super().__init__(
            connections_prefix,
            variables_prefix,
            config_prefix,
            gcp_keyfile_dict,
            gcp_key_path,
            gcp_scopes,
            project_id,
            sep,
            **kwargs)
        self.bucket_name = bucket_name
        self.ignore_mac = ignore_mac

        if not self.bucket_name or self.bucket_name == "":
            self.bucket_name = BUCKET_NAME
            if not self.bucket_name or self.bucket_name == "":
                raise AirflowException("Bucket name not found")

        self.storage_client = storage.Client(project=self.project_id)
        self.kms_client = KeyManagementServiceClient()

        atexit.register(self.cleanup)

    def cleanup(self):
        self.log.info("closing")
        self.storage_client.close()
        self.kms_client.transport.close()

    def get_connection(self, conn_id: str) -> Optional[Connection]:
        file_obj = self._download_blob_to_stream('{}/{}.enc.yaml'.format(self.connections_prefix, conn_id))
        conn_dict = self._decrypt_yaml(file_obj, ignore_mac=self.ignore_mac)
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
        file_obj = self._download_blob_to_stream('{}/{}.enc.yaml'.format(self.variables_prefix, key))
        var_dict = self._decrypt_yaml(file_obj, ignore_mac=self.ignore_mac)
        if var_dict and var_dict.get("value"):
            return var_dict["value"]
        return None

    def _download_blob_to_stream(self, source_blob_name):
        """Downloads a blob to a stream or other file-like object."""

        bucket = self.storage_client.bucket(self.bucket_name)

        blob = bucket.blob(source_blob_name)
        file_obj = io.BytesIO()
        blob.download_to_file(file_obj)
        file_obj.seek(0)

        log.info(f"Downloaded blob {source_blob_name} to file-like object.")

        return file_obj

    def _decrypt_yaml(self, file_obj: io.BytesIO, ignore_mac: bool) -> Optional[Dict]:
        yaml = YAML(typ='safe', pure=True)
        tree = yaml.load(file_obj)
        key, tree = self._get_key(tree)
        sops.check_rotation_needed(tree)
        tree = sops.walk_and_decrypt(tree, key, ignoreMac=ignore_mac)
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
        key = sops.get_key_from_pgp(tree)
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
                log.warning("WARN: KMS resource id not found skipping entry %s" % i)
                continue

            try:
                request = DecryptRequest(name=entry['resource_id'], ciphertext=sops.b64decode(enc))
                response = self.kms_client.decrypt(request=request)
            except Exception as e:
                errors.append("kms %s failed with error: %s " % (entry['resource_id'], e))
                continue
            return response.plaintext

        log.warning("WARN: no KMS client could be accessed:")
        for err in errors:
            log.warning("* %s" % err)
        return None


