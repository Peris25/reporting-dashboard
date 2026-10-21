"""Read a worksheet from a SharePoint/OneDrive workbook via Microsoft Graph.

Uses app-only (client credentials) auth, the same Graph app the mailer uses, with
the Files.Read.All application permission. Given the workbook's sharing URL and a
worksheet name, it returns the used range as a 2D list of string cell values,
ready for reporting.weekly_tracker.

Network calls go through `requests` (already a Streamlit dependency). A session
can be injected for testing.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass

GRAPH = "https://graph.microsoft.com/v1.0"
LOGIN = "https://login.microsoftonline.com"


@dataclass
class GraphConfig:
    tenant_id: str
    client_id: str
    client_secret: str

    @classmethod
    def from_settings(cls, get):
        return cls(
            tenant_id=get("MS_TENANT_ID", ""),
            client_id=get("MS_CLIENT_ID", ""),
            client_secret=get("MS_CLIENT_SECRET", ""),
        )

    def is_configured(self):
        return bool(self.tenant_id and self.client_id and self.client_secret)


def encode_share_url(url):
    """Encode a sharing URL into the Graph /shares '{u!...}' token."""
    encoded = base64.urlsafe_b64encode(url.encode("utf-8")).decode("ascii").rstrip("=")
    return "u!" + encoded


def _session(session):
    if session is not None:
        return session
    import requests  # imported lazily; present via Streamlit

    return requests.Session()


def get_token(config, session=None):
    http = _session(session)
    response = http.post(
        f"{LOGIN}/{config.tenant_id}/oauth2/v2.0/token",
        data={
            "client_id": config.client_id,
            "client_secret": config.client_secret,
            "scope": "https://graph.microsoft.com/.default",
            "grant_type": "client_credentials",
        },
        timeout=30,
    )
    response.raise_for_status()
    return response.json()["access_token"]


def resolve_drive_item(share_url, token, session=None):
    """Return (drive_id, item_id) for a sharing URL."""
    http = _session(session)
    response = http.get(
        f"{GRAPH}/shares/{encode_share_url(share_url)}/driveItem?$select=id,parentReference",
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    return data["parentReference"]["driveId"], data["id"]


def _coerce(value):
    if value is None:
        return ""
    return str(value)


def read_worksheet_values(config, *, share_url, worksheet, session=None):
    """Return the worksheet's used range as a 2D list of string cell values."""
    token = get_token(config, session=session)
    drive_id, item_id = resolve_drive_item(share_url, token, session=session)
    http = _session(session)
    response = http.get(
        f"{GRAPH}/drives/{drive_id}/items/{item_id}/workbook/worksheets"
        f"('{worksheet}')/usedRange(valuesOnly=true)?$select=values",
        headers={"Authorization": f"Bearer {token}"},
        timeout=60,
    )
    response.raise_for_status()
    values = response.json().get("values") or []
    return [[_coerce(cell) for cell in row] for row in values]
