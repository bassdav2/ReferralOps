from __future__ import annotations

from backend.app.documents.object_store import ObjectStoreClient, object_uri, parse_object_uri


def test_object_uri_round_trips_bucket_and_key():
    uri = object_uri("documents", "referrals/400-demo/sample.pdf")

    assert uri == "minio://documents/referrals/400-demo/sample.pdf"
    assert parse_object_uri(uri) == ("documents", "referrals/400-demo/sample.pdf")


def test_object_store_client_signs_path_style_minio_urls():
    client = ObjectStoreClient(
        endpoint="http://localhost:9000",
        access_key="minio",
        secret_key="minio123",
        region="us-east-1",
    )

    url, headers = client._signed_url_and_headers(
        "GET",
        "documents",
        key="referrals/400-demo/sample file.pdf",
    )

    assert url.startswith("http://localhost:9000/documents/referrals/400-demo/sample%20file.pdf")
    assert headers["host"] == "localhost:9000"
    assert "AWS4-HMAC-SHA256" in headers["authorization"]
