"""The ``status://server`` resource.

Reports whether the synthetic dataset is present. Counts only; no customer,
account or merchant detail is exposed here.
"""

from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from ..app.container import Container
from ..config.settings import settings


def get_server_status(container: Container) -> dict[str, Any]:
    """Return a small, non-identifying health summary."""
    dataset_ready = container.dataset_ready()
    transaction_count: int | None = None
    merchant_count: int | None = None

    if dataset_ready:
        try:
            transaction_count = container.transactions.count()
            merchant_count = container.merchants.count()
        except SQLAlchemyError:
            dataset_ready = False

    return {
        "server_name": settings.server_name,
        "server_version": settings.server_version,
        "read_only_evidence_tools": True,
        "dispute_registration": True,
        "dataset_ready": dataset_ready,
        "transaction_count": transaction_count,
        "merchant_count": merchant_count,
        "descope_configured": settings.descope_configured,
        "http_auth": "descope" if settings.descope_configured else "not_configured",
        "data_disclaimer": (
            "All data served here is fictional and synthetically generated. This project is not "
            "affiliated with or representative of any financial institution."
        ),
    }
