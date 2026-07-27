"""SAPI account / quota / subscription reads.

Endpoints (memo § Read endpoints, confirmed against a live session):

* quota   — ``GET /sapi/media?action=get-storage-space&softdeleted=true``
* account — ``GET /sapi/profile?action=get``
* plan    — ``GET /sapi/subscription/plan?action=get``
"""

from __future__ import annotations

from .client import SapiClient
from .models import Account, Plan, PlanList, Quota


class QuotaApi:
    """Account details, storage usage, and subscription plan."""

    def __init__(self, client: SapiClient) -> None:
        self._client = client

    def get_quota(self) -> Quota:
        """``GET /sapi/media?action=get-storage-space&softdeleted=true`` → Quota."""
        data = self._client.get(
            "/media", params={"action": "get-storage-space", "softdeleted": "true"}
        )
        return Quota.model_validate(data)

    def get_account(self) -> Account:
        """``GET /sapi/profile?action=get`` → Account."""
        data = self._client.get("/profile", params={"action": "get"})
        return Account.model_validate(data)

    def get_plan(self) -> list[Plan]:
        """``GET /sapi/subscription/plan?action=get`` → ``data.plans[]``."""
        data = self._client.get("/subscription/plan", params={"action": "get"})
        return PlanList.model_validate(data).plans


__all__ = ["QuotaApi"]
