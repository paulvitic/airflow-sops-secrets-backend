import io
from google.cloud.storage import Client


def _download_to_stream(bucket_name, source_blob_name, project_id):
    """Downloads a blob to a stream or other file-like object."""
    client = Client(project=project_id)
    bucket = client.bucket(bucket_name)

    blob = bucket.blob(source_blob_name)
    file_obj = io.BytesIO()
    blob.download_to_file(file_obj)

    client.close()

    file_obj.seek(0)
    return file_obj
