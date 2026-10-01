"""HTTP client the agent uses to talk to the platform.

Crucial: it authenticates as the USER'S OWN token. There is no elevated key.
If the user lacks permission the server returns 403 and we surface it — the
agent never invents success.
"""

from __future__ import annotations

import httpx


class ApiError(Exception):
    def __init__(self, status_code: int, detail):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"HTTP {status_code}: {detail}")


class PlatformApi:
    def __init__(self, base_url: str, token: str, client: httpx.Client | None = None):
        self.base_url = base_url.rstrip("/")
        self.headers = {"Authorization": f"Bearer {token}"}
        self._client = client or httpx.Client(timeout=10.0)

    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        resp = self._client.request(
            method, f"{self.base_url}{path}", headers=self.headers, **kwargs
        )
        if resp.status_code >= 400:
            try:
                detail = resp.json()
            except Exception:  # noqa: BLE001
                detail = resp.text
            raise ApiError(resp.status_code, detail)
        return resp

    # --- reads -----------------------------------------------------------
    def list_events(self) -> list[dict]:
        return self._request("GET", "/events").json()

    def get_event(self, event_id: int) -> dict:
        return self._request("GET", f"/events/{event_id}").json()

    def list_sessions(self, event_id: int) -> list[dict]:
        return self._request("GET", f"/events/{event_id}/sessions").json()

    def free_rooms(self, event_id: int, start_iso: str, minutes: int) -> list[dict]:
        return self._request(
            "GET",
            f"/events/{event_id}/rooms/free",
            params={"start": start_iso, "minutes": minutes},
        ).json()

    def list_invitations(self, event_id: int, cursor: int | None = None, limit: int = 50):
        params = {"limit": limit}
        if cursor is not None:
            params["cursor"] = cursor
        return self._request("GET", f"/events/{event_id}/invitations", params=params).json()

    def list_members(self, event_id: int) -> dict:
        return self._request("GET", f"/events/{event_id}/members").json()

    # --- writes (each supports dry_run for honest previews) --------------
    def create_session(
        self, event_id: int, title: str, room_name: str, start: str, end: str, dry_run: bool = False
    ) -> dict:
        body = {
            "title": title,
            "room_name": room_name,
            "start_time": start,
            "end_time": end,
        }
        return self._request(
            "POST", f"/events/{event_id}/sessions", params={"dry_run": dry_run}, json=body
        ).json()

    def invite(self, event_id: int, emails: list[str], dry_run: bool = False) -> dict:
        return self._request(
            "POST",
            f"/events/{event_id}/invitations",
            params={"dry_run": dry_run},
            json={"emails": emails},
        ).json()

    def add_member(self, event_id: int, email: str, role: str) -> dict:
        return self._request(
            "POST",
            f"/events/{event_id}/members",
            json={"email": email, "role": role},
        ).json()
