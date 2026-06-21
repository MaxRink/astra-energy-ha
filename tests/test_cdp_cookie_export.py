from tools.astra_cdp_cookie_export import _session_id_from_dom


class FakeCdp:
    def __init__(self, value: str) -> None:
        self.value = value

    def command(self, method: str, params: dict | None = None) -> dict:
        assert method == "Runtime.evaluate"
        assert params is not None
        return {"result": {"value": self.value}}


def test_session_id_from_dom_returns_embedded_dashboard_session_id() -> None:
    session_id = "0123456789abcdef0123456789abcdef"

    assert _session_id_from_dom(FakeCdp(session_id)) == session_id


def test_session_id_from_dom_ignores_missing_session_id() -> None:
    assert _session_id_from_dom(FakeCdp("")) is None
