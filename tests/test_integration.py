import json
import unittest
import os
from airflow_sops.secrets_backend import GcsSopsSecretsBackend

# env_path = Path('.')/tests/.env
# load_dotenv(dotenv_path=env_path)


class TestGcsSopsSecretsBackend(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from dotenv import load_dotenv
        load_dotenv(".env-test")

    def test_gcp_conn(self):
        bucket_name = os.getenv("INTEGRATION_TEST_BUCKET_NAME")
        if not bucket_name:
            self.skipTest(Exception("integration test requires bucket name"))

        manager = GcsSopsSecretsBackend(bucket_name=bucket_name)
        conn = manager.get_connection(conn_id="gcp_conn")
        self.assertIsNotNone(conn)
        self.assertEqual("gcp_conn", conn.conn_id)

        extra = conn.extra_dejson
        key_file_string = extra["extra__google_cloud_platform__keyfile_dict"]
        key_file_dict = json.loads(key_file_string)
        self.assertEqual("service_account", key_file_dict["type"])

        conn_uri = manager.get_conn_uri(conn_id="gcp_conn")
        self.assertIsNotNone(conn_uri)

        var_val = manager.get_variable("invoice_gsheet_id")
        self.assertIsNotNone(var_val)

    def test_personio(self):
        bucket_name = os.getenv("INTEGRATION_TEST_BUCKET_NAME")
        if not bucket_name:
            self.skipTest(Exception("integration test requires bucket name"))

        manager = GcsSopsSecretsBackend(bucket_name=bucket_name)
        conn = manager.get_connection(conn_id="personio")
        self.assertIsNotNone(conn)

    def test_slack_channel(self):
        bucket_name = os.getenv("INTEGRATION_TEST_BUCKET_NAME")
        if not bucket_name:
            self.skipTest(Exception("integration test requires bucket name"))

        manager = GcsSopsSecretsBackend(bucket_name=bucket_name)
        conn = manager.get_connection(conn_id="slack_channel")
        self.assertIsNotNone(conn)


if __name__ == '__main__':
    unittest.main()

