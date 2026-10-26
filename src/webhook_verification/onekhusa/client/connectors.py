from __future__ import annotations

MIN_CONNECTOR_ID = 1


class InvalidConnectorError(ValueError):
    pass


def validate_connector_id(connector_id: object) -> int:
    """Return a valid OneKhusa connector identifier or raise."""

    if (
        isinstance(connector_id, bool)
        or not isinstance(connector_id, int)
        or connector_id < MIN_CONNECTOR_ID
    ):
        raise InvalidConnectorError(
            f"connectorId must be an integer greater than or equal to {MIN_CONNECTOR_ID}"
        )
    return connector_id
