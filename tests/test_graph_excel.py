import base64
import json

from reporting.graph_excel import GraphConfig, encode_share_url, read_worksheet_values


def test_encode_share_url():
    token = encode_share_url("https://example.sharepoint.com/x.xlsx?a=b")
    assert token.startswith("u!")
    decoded = base64.urlsafe_b64decode(token[2:] + "==").decode()
    assert decoded == "https://example.sharepoint.com/x.xlsx?a=b"


def test_graph_config_from_settings():
    cfg = GraphConfig.from_settings(lambda k, d="": {"MS_TENANT_ID": "t", "MS_CLIENT_ID": "c", "MS_CLIENT_SECRET": "s"}.get(k, d))
    assert cfg.is_configured()
    assert not GraphConfig.from_settings(lambda k, d="": d).is_configured()


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class _FakeSession:
    def __init__(self):
        self.calls = []

    def post(self, url, data=None, timeout=None):
        self.calls.append(("POST", url))
        return _Resp({"access_token": "tok"})

    def get(self, url, headers=None, timeout=None):
        self.calls.append(("GET", url))
        if "/driveItem" in url:
            return _Resp({"id": "ITEM1", "parentReference": {"driveId": "DRIVE1"}})
        return _Resp({"values": [["A", 1, None], ["B", "", 2.5]]})


def test_read_worksheet_values_coerces_cells():
    cfg = GraphConfig("t", "c", "s")
    session = _FakeSession()
    values = read_worksheet_values(cfg, share_url="https://x/y.xlsx", worksheet="Sheet", session=session)
    assert values == [["A", "1", ""], ["B", "", "2.5"]]
    # token, driveItem, usedRange
    assert [m for m, _ in session.calls] == ["POST", "GET", "GET"]
    assert any("usedRange" in u for _, u in session.calls)
