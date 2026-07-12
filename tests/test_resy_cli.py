import json
from argparse import Namespace
from unittest.mock import MagicMock

import pytest
from requests import HTTPError

import resy_cli
from resy_bot.api_access import ResyApiAccess


def test_setup_writes_credentials_with_payment_method(tmp_path):
    creds = tmp_path / "creds.json"
    args = Namespace(
        api_key="my-key",
        token="my-token",
        payment_method_id=123,
        email=None,
        password=None,
        credentials=str(creds),
    )

    result = resy_cli.cmd_setup(args)

    assert result["status"] == "saved"
    assert result["path"] == str(creds)
    assert result["has_payment_method"] is True

    data = json.loads(creds.read_text())
    assert data["api_key"] == "my-key"
    assert data["token"] == "my-token"
    assert data["payment_method_id"] == 123


def test_setup_without_payment_method(tmp_path):
    creds = tmp_path / "creds.json"
    args = Namespace(
        api_key="k",
        token="t",
        payment_method_id=None,
        email=None,
        password=None,
        credentials=str(creds),
    )

    result = resy_cli.cmd_setup(args)

    assert result["has_payment_method"] is False

    data = json.loads(creds.read_text())
    assert "payment_method_id" not in data
    assert data == {"api_key": "k", "token": "t"}


def test_search_venues_parses_hits():
    session = MagicMock()
    resp_mock = MagicMock()
    resp_mock.ok = True
    resp_mock.json.return_value = {
        "search": {
            "hits": [
                {"id": {"resy": 443}, "name": "Carbone", "locality": "New York"}
            ]
        }
    }
    session.post.return_value = resp_mock

    api_access = ResyApiAccess(session)

    result = api_access.search_venues("carbone")

    assert result == [{"id": 443, "name": "Carbone", "location": "New York"}]


def test_search_venues_skips_malformed_and_defaults():
    session = MagicMock()
    resp_mock = MagicMock()
    resp_mock.ok = True
    resp_mock.json.return_value = {
        "search": {
            "hits": [
                {"objectID": 99, "name": "Fallback", "region": "Brooklyn"},
                None,  # malformed -> skipped
            ]
        }
    }
    session.post.return_value = resp_mock

    api_access = ResyApiAccess(session)

    result = api_access.search_venues("x", per_page=2)

    assert result == [{"id": 99, "name": "Fallback", "location": "Brooklyn"}]


def test_get_user_returns_json():
    session = MagicMock()
    resp_mock = MagicMock()
    resp_mock.ok = True
    resp_mock.json.return_value = {"payment_methods": [{"id": 1}]}
    session.get.return_value = resp_mock

    api_access = ResyApiAccess(session)

    assert api_access.get_user() == {"payment_methods": [{"id": 1}]}


def test_get_user_raises_on_bad_response():
    session = MagicMock()
    resp_mock = MagicMock()
    resp_mock.ok = False
    session.get.return_value = resp_mock

    api_access = ResyApiAccess(session)

    with pytest.raises(HTTPError):
        api_access.get_user()
