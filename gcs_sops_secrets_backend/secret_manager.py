from os import environ
from typing import Optional, List, Dict

from google.cloud import storage
from google.cloud.kms import KeyManagementServiceClient, DecryptRequest
from google.auth import default as default_auth
from google.auth.exceptions import DefaultCredentialsError

from airflow.exceptions import AirflowException
from airflow.secrets.base_secrets import BaseSecretsBackend
from airflow.utils.log.logging_mixin import LoggingMixin
from airflow.models.connection import Connection

from ruamel.yaml import YAML

import sops
import io
import logging

log = logging.getLogger(__name__)

# Composer environment key for bucket name.
BUCKET_NAME = environ.get('GCS_BUCKET')


def download_blob_to_stream(bucket_name, source_blob_name):
    """Downloads a blob to a stream or other file-like object."""
    storage_client = storage.Client(project=None)

    bucket = storage_client.bucket(bucket_name)

    blob = bucket.blob(source_blob_name)
    file_obj = io.BytesIO()
    blob.download_to_file(file_obj)

    log.info(f"Downloaded blob {source_blob_name} to file-like object.")
    storage_client.close()

    file_obj.seek(0)
    return file_obj


def decrypt_yaml(file_obj: io.BytesIO, ignore_mac: bool) -> Optional[Dict]:
    yaml = YAML(typ='safe', pure=True)
    tree = yaml.load(file_obj)
    key, tree = get_key(tree)
    sops.check_rotation_needed(tree)
    tree = sops.walk_and_decrypt(tree, key, ignoreMac=ignore_mac)
    if tree:
        tree.pop('sops', None)
        return dict(tree)
    return None


def get_key_from_kms(tree):
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
            client = KeyManagementServiceClient()
        except Exception as e:
            errors.append("no kms client could be obtained for entry %s, error was: %s" %
                          (entry['resource_id'], e))
            continue

        try:
            request = DecryptRequest(name=entry['resource_id'], ciphertext=sops.b64decode(enc))
            response = client.decrypt(request=request)
        except Exception as e:
            errors.append("kms %s failed with error: %s " % (entry['resource_id'], e))
            continue
        return response.plaintext

    log.warning("WARN: no KMS client could be accessed:")
    for err in errors:
        log.warning("* %s" % err)
    return None


def get_key(tree):
    """Obtain a 256 bits symetric key.

    If the document contain an encrypted key, try to decrypt it using
    KMS or PGP. Otherwise, generate a new random key.

    """
    key = get_key_from_kms(tree)
    if not (key is None):
        return key, tree
    key = sops.get_key_from_pgp(tree)
    if not (key is None):
        return key, tree
    raise AirflowException("could not retrieve a key to encrypt/decrypt the tree")


class GcsSopsSecretsBackend(BaseSecretsBackend, LoggingMixin):
    def __init__(
            self,
            bucket_name: str = None,
            root_key: str = "sops",
            connections_key: str = "connections",
            variables_key: str = "variables",
            ignore_mac: bool = True,
            **kwargs
    ) -> None:
        super().__init__(**kwargs)
        self.bucket_name = bucket_name
        self.root_key = root_key
        self.connections_key = connections_key
        self.variables_key = variables_key
        self.ignore_mac = ignore_mac

        if not self.bucket_name or self.bucket_name == "":
            self.bucket_name = BUCKET_NAME
            if not self.bucket_name or self.bucket_name == "":
                raise AirflowException("Bucket name not found")

        try:
            self.credentials, self.project_id = default_auth()
        except (DefaultCredentialsError, FileNotFoundError):
            self.log.exception(
                'Unable to load credentials for GCP Secret Manager. '
                'Make sure that the keyfile path, dictionary, or GOOGLE_APPLICATION_CREDENTIALS '
                'environment variable is correct and properly configured.'
            )

    def get_connection(self, conn_id: str) -> Optional[Connection]:
        file_obj = download_blob_to_stream(self.bucket_name,
                                           '{}/{}/{}.enc.yaml'.format(self.root_key,
                                                                      self.connections_key,
                                                                      conn_id))
        conn_dict = decrypt_yaml(file_obj, ignore_mac=self.ignore_mac)
        if conn_dict:
            conn = Connection(conn_id=conn_id, **conn_dict)
            return conn
        return None

    def get_connections(self, conn_id: str) -> List['Connection']:
        """
        Return connection object with a given ``conn_id``.

        :param conn_id: connection id
        :type conn_id: str
        """
        self.log.warning(
            "This method is deprecated. Please use "
            "`airflow.secrets.base_secrets.BaseSecretsBackend.get_connection`.",
            PendingDeprecationWarning,
            stacklevel=2,
        )
        conn = self.get_connection(conn_id=conn_id)
        if conn:
            return [conn]
        return []

    def get_conn_uri(self, conn_id: str) -> Optional[str]:
        conn = self.get_connection(conn_id)
        if conn:
            return conn.get_uri()
        return None

    def get_variable(self, key: str) -> Optional[str]:
        file_obj = download_blob_to_stream(self.bucket_name,
                                           '{}/{}/{}.enc.yaml'.format(self.root_key,
                                                                      self.variables_key,
                                                                      key))
        var_dict = decrypt_yaml(file_obj, ignore_mac=self.ignore_mac)
        if var_dict and var_dict.get("value"):
            return var_dict["value"]
        return None

