"""Payment domain and application layer.

This package models a push payment and orchestrates OneKhusa calls. It must not
import ``httpx``, ``fastapi`` or the ``onekhusa`` adapter; provider and
framework details are supplied through the ports in :mod:`payments.ports`.
"""

from __future__ import annotations
