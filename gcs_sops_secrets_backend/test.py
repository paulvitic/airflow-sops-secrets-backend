from secret_manager import GcsSopsSecretsBackend
manager = GcsSopsSecretsBackend(bucket_name='europe-west1-cm-staging-com-01ae7fff-bucket')
conn = manager.get_connection(conn_id="here")
if not conn:
    raise Exception("failed")

conn_uri = manager.get_conn_uri(conn_id="here")
if not conn_uri:
    raise Exception("failed")
print(conn_uri)

var_val = manager.get_variable("invoice_gsheet_id")
if not var_val:
    raise Exception("failed")
print(var_val)

