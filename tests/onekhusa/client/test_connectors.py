from __future__ import annotations

import pytest

from webhook_verification.onekhusa.client.connectors import (
    InvalidConnectorError,
    validate_connector_id,
)


def test_accepts_a_positive_connector_identifier() -> None:
    assert validate_connector_id(892353) == 892353


@pytest.mark.parametrize("value", [0, -1, True, "892353", 1.5, None])
def test_rejects_invalid_connector_identifiers(value: object) -> None:
    with pytest.raises(InvalidConnectorError):
        validate_connector_id(value)
