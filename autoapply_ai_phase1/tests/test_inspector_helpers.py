import pytest
from app.services.job_page_inspector import detect_ats, _assert_public_http_url, UnsafeURL


def test_detect_greenhouse():
    assert detect_ats("https://boards.greenhouse.io/acme/jobs/123", "") == "greenhouse"


def test_detect_lever():
    assert detect_ats("https://jobs.lever.co/acme/123", "") == "lever"


def test_blocks_localhost():
    with pytest.raises(UnsafeURL):
        _assert_public_http_url("http://127.0.0.1/admin")


def test_blocks_non_http():
    with pytest.raises(UnsafeURL):
        _assert_public_http_url("file:///etc/passwd")
