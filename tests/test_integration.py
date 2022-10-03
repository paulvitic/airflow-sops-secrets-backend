import unittest
import os
from dotenv import load_dotenv
from pathlib import Path
from airflow_sops.secrets_backend import GcsSopsSecretsBackend

env_path = Path('.')/'tests'/'.env'
load_dotenv(dotenv_path=env_path)


class TestGcsSopsSecretsBackend(unittest.TestCase):

    def test(self):
        bucket_name = os.getenv("INTEGRATION_TEST_BUCKET_NAME")
        if not bucket_name:
            self.skipTest(Exception("integration test requires bucket name"))

        manager = GcsSopsSecretsBackend(bucket_name=bucket_name)
        conn = manager.get_connection(conn_id="here")
        self.assertIsNotNone(conn)

        conn_uri = manager.get_conn_uri(conn_id="here")
        self.assertIsNotNone(conn_uri)

        var_val = manager.get_variable("invoice_gsheet_id")
        self.assertIsNotNone(var_val)


if __name__ == '__main__':
    unittest.main()

