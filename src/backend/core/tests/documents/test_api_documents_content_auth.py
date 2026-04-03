"""
Test content-auth authorization API endpoint in docs core app.
"""

from io import BytesIO
from urllib.parse import urlparse
from uuid import uuid4

from django.conf import settings
from django.core.files.storage import default_storage
from django.utils import timezone

import pytest
import requests
from freezegun import freeze_time
from rest_framework.test import APIClient

from core import factories, models
from core.tests.conftest import TEAM, USER, VIA

pytestmark = pytest.mark.django_db


def _content_url(doc_id):
    return f"http://localhost/documents-content/{doc_id!s}/"


def _put_content(doc_id, body=b"document content"):
    key = f"{doc_id!s}/file"
    default_storage.connection.meta.client.put_object(
        Bucket=default_storage.bucket_name,
        Key=key,
        Body=BytesIO(body),
        ContentType="application/octet-stream",
    )
    return key


def test_api_documents_content_auth_unknown_document():
    """
    Trying to retrieve the content of a document ID that does not exist
    should return 403 without creating it (no regression test).
    """
    doc_id = uuid4()
    original_url = _content_url(doc_id)

    response = APIClient().get(
        "/api/v1.0/documents/content-auth/", HTTP_X_ORIGINAL_URL=original_url
    )

    assert response.status_code == 403
    assert models.Document.objects.exists() is False


def test_api_documents_content_auth_missing_original_url():
    """Requests without the X-Original-URL header should return 403."""
    response = APIClient().get("/api/v1.0/documents/content-auth/")

    assert response.status_code == 403


def test_api_documents_content_auth_invalid_url_pattern():
    """Requests with an URL not matching the document content pattern should return 403."""
    response = APIClient().get(
        "/api/v1.0/documents/content-auth/",
        HTTP_X_ORIGINAL_URL="http://localhost/documents-content/not-a-uuid/",
    )

    assert response.status_code == 403


def test_api_documents_content_auth_anonymous_public():
    """Anonymous users should be allowed to retrieve content of public documents."""
    document = factories.DocumentFactory(link_reach="public")
    key = _put_content(document.id)

    original_url = _content_url(document.id)
    now = timezone.now()
    with freeze_time(now):
        response = APIClient().get(
            "/api/v1.0/documents/content-auth/", HTTP_X_ORIGINAL_URL=original_url
        )

    assert response.status_code == 200

    authorization = response["Authorization"]
    assert "AWS4-HMAC-SHA256 Credential=" in authorization
    assert (
        "SignedHeaders=host;x-amz-content-sha256;x-amz-date, Signature="
        in authorization
    )
    assert response["X-Amz-Date"] == now.strftime("%Y%m%dT%H%M%SZ")

    # Verify the returned headers actually allow fetching the content from S3
    s3_url = urlparse(settings.AWS_S3_ENDPOINT_URL)
    file_url = f"{settings.AWS_S3_ENDPOINT_URL}/impress-media-storage/{key}"
    s3_response = requests.get(
        file_url,
        headers={
            "authorization": authorization,
            "x-amz-date": response["x-amz-date"],
            "x-amz-content-sha256": response["x-amz-content-sha256"],
            "Host": f"{s3_url.hostname}:{s3_url.port}",
        },
        timeout=1,
    )
    assert s3_response.content == b"document content"


@pytest.mark.parametrize("reach", ["authenticated", "restricted"])
def test_api_documents_content_auth_anonymous_non_public(reach):
    """
    Anonymous users should not be allowed to retrieve content of documents
    with link reach set to authenticated or restricted.
    """
    document = factories.DocumentFactory(link_reach=reach)

    response = APIClient().get(
        "/api/v1.0/documents/content-auth/",
        HTTP_X_ORIGINAL_URL=_content_url(document.id),
    )

    assert response.status_code == 403
    assert "Authorization" not in response


@pytest.mark.parametrize("reach", ["public", "authenticated"])
def test_api_documents_content_auth_authenticated_accessible(reach):
    """
    Authenticated users should be allowed to retrieve content of documents
    with public or authenticated link reach.
    """
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)

    document = factories.DocumentFactory(link_reach=reach)
    _put_content(document.id)

    original_url = _content_url(document.id)
    now = timezone.now()
    with freeze_time(now):
        response = client.get(
            "/api/v1.0/documents/content-auth/",
            HTTP_X_ORIGINAL_URL=original_url,
        )

    assert response.status_code == 200
    assert "AWS4-HMAC-SHA256 Credential=" in response["Authorization"]
    assert response["X-Amz-Date"] == now.strftime("%Y%m%dT%H%M%SZ")


def test_api_documents_content_auth_authenticated_restricted():
    """
    Authenticated users without explicit access should not be allowed to retrieve
    content of restricted documents.
    """
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)

    document = factories.DocumentFactory(link_reach="restricted")

    response = client.get(
        "/api/v1.0/documents/content-auth/",
        HTTP_X_ORIGINAL_URL=_content_url(document.id),
    )

    assert response.status_code == 403
    assert "Authorization" not in response


@pytest.mark.parametrize("via", VIA)
def test_api_documents_content_auth_related(via, mock_user_teams):
    """
    Users who have explicit access to a document, whatever the role, should be able to
    retrieve its content.
    """
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)

    document = factories.DocumentFactory(link_reach="restricted")
    key = _put_content(document.id)

    if via == USER:
        factories.UserDocumentAccessFactory(document=document, user=user)
    elif via == TEAM:
        mock_user_teams.return_value = ["lasuite", "unknown"]
        factories.TeamDocumentAccessFactory(document=document, team="lasuite")

    original_url = _content_url(document.id)
    now = timezone.now()
    with freeze_time(now):
        response = client.get(
            "/api/v1.0/documents/content-auth/",
            HTTP_X_ORIGINAL_URL=original_url,
        )

    assert response.status_code == 200

    authorization = response["Authorization"]
    assert "AWS4-HMAC-SHA256 Credential=" in authorization
    assert (
        "SignedHeaders=host;x-amz-content-sha256;x-amz-date, Signature="
        in authorization
    )
    assert response["X-Amz-Date"] == now.strftime("%Y%m%dT%H%M%SZ")

    # Verify the returned headers actually allow fetching the content from S3
    s3_url = urlparse(settings.AWS_S3_ENDPOINT_URL)
    file_url = f"{settings.AWS_S3_ENDPOINT_URL}/impress-media-storage/{key}"
    s3_response = requests.get(
        file_url,
        headers={
            "authorization": authorization,
            "x-amz-date": response["x-amz-date"],
            "x-amz-content-sha256": response["x-amz-content-sha256"],
            "Host": f"{s3_url.hostname}:{s3_url.port}",
        },
        timeout=1,
    )
    assert s3_response.content == b"document content"
