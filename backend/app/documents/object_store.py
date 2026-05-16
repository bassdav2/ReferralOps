from __future__ import annotations

import hashlib
import hmac
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote, urlparse
from xml.etree import ElementTree

import httpx

from backend.app.core.config import get_settings

EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()
SERVICE = "s3"


@dataclass(frozen=True)
class ObjectInfo:
    key: str
    size_bytes: int
    etag: str | None = None


def object_uri(bucket: str, key: str) -> str:
    return f"minio://{bucket}/{key.lstrip('/')}"


def parse_object_uri(uri: str) -> tuple[str, str]:
    parsed = urlparse(uri)
    if parsed.scheme != "minio" or not parsed.netloc or not parsed.path.strip("/"):
        raise ValueError(f"Unsupported object storage URI: {uri}")
    return parsed.netloc, parsed.path.lstrip("/")


def is_object_uri(value: str | None) -> bool:
    return bool(value and value.startswith("minio://"))


def _sign(key: bytes, message: str) -> bytes:
    return hmac.new(key, message.encode("utf-8"), hashlib.sha256).digest()


def _sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_query(params: dict[str, str]) -> str:
    return "&".join(
        f"{quote(key, safe='-_.~')}={quote(value, safe='-_.~')}" for key, value in sorted(params.items())
    )


class ObjectStoreClient:
    def __init__(
        self,
        *,
        endpoint: str,
        access_key: str,
        secret_key: str,
        region: str,
        timeout: float = 60.0,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.access_key = access_key
        self.secret_key = secret_key
        self.region = region
        self.timeout = timeout

    def list_objects(self, bucket: str, prefix: str = "") -> list[ObjectInfo]:
        objects: list[ObjectInfo] = []
        token: str | None = None
        while True:
            params = {"list-type": "2", "prefix": prefix}
            if token:
                params["continuation-token"] = token
            response = self._request("GET", bucket, params=params)
            root = ElementTree.fromstring(response.content)
            namespace = root.tag.partition("}")[0].strip("{")
            ns = {"s3": namespace} if namespace else {}
            contents = root.findall("s3:Contents", ns) if ns else root.findall("Contents")
            for item in contents:
                key = _xml_text(item, "Key", ns)
                if not key:
                    continue
                size = int(_xml_text(item, "Size", ns) or "0")
                etag = (_xml_text(item, "ETag", ns) or "").strip('"') or None
                objects.append(ObjectInfo(key=key, size_bytes=size, etag=etag))
            truncated = (_xml_text(root, "IsTruncated", ns) or "false").lower() == "true"
            token = _xml_text(root, "NextContinuationToken", ns)
            if not truncated or not token:
                break
        return objects

    def download_object(self, bucket: str, key: str, target: Path) -> None:
        url, headers = self._signed_url_and_headers("GET", bucket, key=key)
        with httpx.stream("GET", url, headers=headers, timeout=self.timeout) as response:
            response.raise_for_status()
            with target.open("wb") as handle:
                for chunk in response.iter_bytes():
                    handle.write(chunk)

    def upload_object(
        self,
        bucket: str,
        key: str,
        content: bytes,
        *,
        content_type: str = "application/octet-stream",
    ) -> None:
        payload_hash = hashlib.sha256(content).hexdigest()
        self._request(
            "PUT",
            bucket,
            key=key,
            content=content,
            content_type=content_type,
            payload_sha256=payload_hash,
        )

    def delete_object(self, bucket: str, key: str) -> None:
        self._request("DELETE", bucket, key=key)

    def sha256_object(self, bucket: str, key: str) -> str:
        hasher = hashlib.sha256()
        url, headers = self._signed_url_and_headers("GET", bucket, key=key)
        with httpx.stream("GET", url, headers=headers, timeout=self.timeout) as response:
            response.raise_for_status()
            for chunk in response.iter_bytes():
                hasher.update(chunk)
        return hasher.hexdigest()

    def _request(
        self,
        method: str,
        bucket: str,
        *,
        key: str | None = None,
        params: dict[str, str] | None = None,
        content: bytes | None = None,
        content_type: str | None = None,
        payload_sha256: str | None = None,
    ) -> httpx.Response:
        extra_headers = {"content-type": content_type} if content_type else None
        url, headers = self._signed_url_and_headers(
            method,
            bucket,
            key=key,
            params=params,
            payload_sha256=payload_sha256,
            extra_headers=extra_headers,
        )
        response = httpx.request(method, url, headers=headers, content=content, timeout=self.timeout)
        response.raise_for_status()
        return response

    def _signed_url_and_headers(
        self,
        method: str,
        bucket: str,
        *,
        key: str | None = None,
        params: dict[str, str] | None = None,
        payload_sha256: str | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> tuple[str, dict[str, str]]:
        parsed = urlparse(self.endpoint)
        host = parsed.netloc
        path_parts = [quote(bucket, safe="-_.~")]
        if key:
            path_parts.append(quote(key.lstrip("/"), safe="/-_.~"))
        canonical_uri = "/" + "/".join(path_parts)
        query = _canonical_query(params or {})
        now = datetime.now(UTC)
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        date_stamp = now.strftime("%Y%m%d")
        credential_scope = f"{date_stamp}/{self.region}/{SERVICE}/aws4_request"
        payload_hash = payload_sha256 or EMPTY_SHA256
        headers = {
            "host": host,
            "x-amz-content-sha256": payload_hash,
            "x-amz-date": amz_date,
        }
        if extra_headers:
            headers.update({name.lower(): value for name, value in extra_headers.items()})
        signed_headers = ";".join(sorted(headers))
        canonical_headers = "".join(f"{name}:{headers[name]}\n" for name in sorted(headers))
        canonical_request = "\n".join(
            [method, canonical_uri, query, canonical_headers, signed_headers, payload_hash]
        )
        string_to_sign = "\n".join(
            ["AWS4-HMAC-SHA256", amz_date, credential_scope, _sha256_hex(canonical_request)]
        )
        signing_key = _sign(("AWS4" + self.secret_key).encode("utf-8"), date_stamp)
        signing_key = _sign(signing_key, self.region)
        signing_key = _sign(signing_key, SERVICE)
        signing_key = _sign(signing_key, "aws4_request")
        signature = hmac.new(signing_key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
        headers["authorization"] = (
            f"AWS4-HMAC-SHA256 Credential={self.access_key}/{credential_scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        )
        url = f"{self.endpoint}{canonical_uri}"
        if query:
            url = f"{url}?{query}"
        return url, headers


def _xml_text(element: ElementTree.Element, name: str, ns: dict[str, str]) -> str | None:
    child = element.find(f"s3:{name}", ns) if ns else element.find(name)
    return child.text if child is not None else None


def get_object_store_client() -> ObjectStoreClient:
    settings = get_settings()
    return ObjectStoreClient(
        endpoint=settings.object_store_endpoint,
        access_key=settings.object_store_access_key,
        secret_key=settings.object_store_secret_key,
        region=settings.object_store_region,
        timeout=settings.object_store_timeout_seconds,
    )


def sha256_object_uri(uri: str) -> str:
    bucket, key = parse_object_uri(uri)
    return get_object_store_client().sha256_object(bucket, key)


@contextmanager
def object_uri_to_temp_file(uri: str) -> Iterator[Path]:
    bucket, key = parse_object_uri(uri)
    suffix = Path(key).suffix
    handle = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    temp_path = Path(handle.name)
    handle.close()
    try:
        get_object_store_client().download_object(bucket, key, temp_path)
        yield temp_path
    finally:
        temp_path.unlink(missing_ok=True)
