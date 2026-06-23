from autoresearch.observability import (
    DependencyStatus,
    diagnose_requests_dependency_set,
)


def test_requests_dependency_diagnostic_accepts_locked_poetry_set() -> None:
    diagnostic = diagnose_requests_dependency_set(
        {
            "requests": "2.32.5",
            "urllib3": "2.7.0",
            "charset-normalizer": "3.4.7",
            "chardet": None,
        }
    )

    assert diagnostic.status is DependencyStatus.OK
    assert diagnostic.blocks_doctor is False
    assert "requests 2.32.5" in diagnostic.detail
    assert "chardet not installed" in diagnostic.detail


def test_requests_dependency_diagnostic_warns_on_unsupported_chardet() -> None:
    diagnostic = diagnose_requests_dependency_set(
        {
            "requests": "2.31.0",
            "urllib3": "2.7.0",
            "charset-normalizer": "3.4.7",
            "chardet": "7.4.3",
        }
    )

    assert diagnostic.status is DependencyStatus.WARN
    assert diagnostic.blocks_doctor is False
    assert "chardet should be >=3.0.2 and <6" in diagnostic.detail


def test_requests_dependency_diagnostic_fails_when_requests_is_missing() -> None:
    diagnostic = diagnose_requests_dependency_set(
        {
            "requests": None,
            "urllib3": "2.7.0",
            "charset-normalizer": "3.4.7",
            "chardet": None,
        }
    )

    assert diagnostic.status is DependencyStatus.FAIL
    assert diagnostic.blocks_doctor is True
    assert "requests is declared but not installed" in diagnostic.detail
