"""
test_utils.py — Unit tests for utility functions.
"""
import time
import pytest
from src.common.utils import (
    build_api_url, build_lambda_arn, build_role_arn,
    merge_env_vars, retry, sanitize_name
)
from src.common.exceptions import RetryExhaustedError


class TestSanitizeName:
    def test_lowercase(self):
        assert sanitize_name("MyCompany") == "mycompany"

    def test_spaces_become_hyphens(self):
        assert sanitize_name("My Company") == "my-company"

    def test_special_chars_removed(self):
        # sanitize_name strips trailing hyphens — "ACT Ltd.!" → "act-ltd"
        assert sanitize_name("ACT Ltd.!") == "act-ltd"

    def test_max_length(self):
        result = sanitize_name("a" * 100, max_length=10)
        assert len(result) == 10

    def test_no_leading_trailing_hyphens(self):
        result = sanitize_name("--test--")
        assert not result.startswith("-")
        assert not result.endswith("-")


class TestARNBuilders:
    def test_lambda_arn(self):
        arn = build_lambda_arn("eu-central-1", "123456789012", "my-func")
        assert arn == "arn:aws:lambda:eu-central-1:123456789012:function:my-func"

    def test_role_arn(self):
        arn = build_role_arn("123456789012", "my-role")
        assert arn == "arn:aws:iam::123456789012:role/my-role"

    def test_api_url(self):
        url = build_api_url("abc123", "eu-central-1", "dev")
        assert url == "https://abc123.execute-api.eu-central-1.amazonaws.com/dev"


class TestMergeEnvVars:
    def test_overrides_take_precedence(self):
        base = {"KEY": "old", "OTHER": "value"}
        overrides = {"KEY": "new"}
        result = merge_env_vars(base, overrides)
        assert result["KEY"] == "new"
        assert result["OTHER"] == "value"

    def test_values_stringified(self):
        result = merge_env_vars({}, {"NUM": 42})  # type: ignore[arg-type]
        assert result["NUM"] == "42"


class TestRetryDecorator:
    def test_succeeds_on_first_try(self):
        @retry(max_attempts=3)
        def success():
            return "ok"
        assert success() == "ok"

    def test_retries_and_succeeds(self):
        attempts = []

        @retry(max_attempts=3, delay_seconds=0.01)
        def flaky():
            attempts.append(1)
            if len(attempts) < 2:
                raise ValueError("fail")
            return "ok"

        assert flaky() == "ok"
        assert len(attempts) == 2

    def test_exhausted_raises(self):
        @retry(max_attempts=2, delay_seconds=0.01)
        def always_fails():
            raise ValueError("always")

        with pytest.raises(RetryExhaustedError):
            always_fails()
