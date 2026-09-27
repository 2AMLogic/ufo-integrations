"""The client-server API calls the surface makes, as the bot user.

The access token rides the `Authorization` header and nothing else — never a query string, an
exception message, or a `repr` — so no log line the surface writes can carry it. A failure names the
endpoint, the HTTP status, and the Matrix `errcode`; the response body is the homeserver's text and
is not repeated."""

from collections.abc import Mapping
from types import TracebackType
from typing import Any, Self
from urllib.parse import quote

import httpx

from ufo_ext_matrix.events import SYNC_FILTER

CLIENT_PATH = "/_matrix/client/v3"
SYNC_TIMEOUT_MS = 30_000
REQUEST_TIMEOUT_SECONDS = 20.0


class MatrixError(Exception):
    """A homeserver answer other than success. `retry_after_ms` is the homeserver's own ask on a
    rate limit, so a retry waits as long as it was told to."""

    def __init__(
        self, endpoint: str, status: int, errcode: str | None, retry_after_ms: int | None
    ) -> None:
        self.endpoint = endpoint
        self.status = status
        self.errcode = errcode
        self.retry_after_ms = retry_after_ms
        super().__init__(f"{endpoint} answered {status} {errcode or ''}".rstrip())

    @property
    def unauthorized(self) -> bool:
        return self.status == 401 or self.errcode == "M_UNKNOWN_TOKEN"


class MatrixClient:
    """One bot user's session on one homeserver. `transport` is the seam a test hands a fake
    homeserver through; a deploy leaves it unset."""

    def __init__(
        self,
        homeserver: str,
        access_token: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._http = httpx.AsyncClient(
            base_url=homeserver.rstrip("/") + CLIENT_PATH,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=httpx.Timeout(REQUEST_TIMEOUT_SECONDS + SYNC_TIMEOUT_MS / 1000),
            transport=transport,
        )

    def __repr__(self) -> str:
        return f"MatrixClient({self._http.base_url!s})"

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self._http.aclose()

    async def whoami(self) -> str:
        answer = await self._call("GET", "/account/whoami", "whoami")
        user_id = answer.get("user_id")
        if not isinstance(user_id, str):
            raise MatrixError("whoami", 200, "M_BAD_JSON", None)
        return user_id

    async def sync(self, since: str | None) -> Mapping[str, Any]:
        """One long poll. The first sync of a stream (`since` None) returns at once: it only fixes
        where the stream stands."""
        params: dict[str, str | int] = {
            "filter": SYNC_FILTER,
            "timeout": 0 if since is None else SYNC_TIMEOUT_MS,
        }
        if since is not None:
            params["since"] = since
        return await self._call("GET", "/sync", "sync", params=params)

    async def send_text(self, room_id: str, txn_id: str, body: str) -> str:
        """Send one `m.text` message under a caller-chosen transaction id and return its event id.
        The homeserver answers a repeated transaction id with the event it already created."""
        path = (
            f"/rooms/{quote(room_id, safe='')}/send/m.room.message/{quote(txn_id, safe='')}"
        )
        answer = await self._call(
            "PUT", path, "send", json={"msgtype": "m.text", "body": body}
        )
        event_id = answer.get("event_id")
        if not isinstance(event_id, str):
            raise MatrixError("send", 200, "M_BAD_JSON", None)
        return event_id

    async def join(self, room_id: str) -> None:
        await self._call("POST", f"/join/{quote(room_id, safe='')}", "join", json={})

    async def joined_members(self, room_id: str) -> frozenset[str]:
        answer = await self._call(
            "GET", f"/rooms/{quote(room_id, safe='')}/joined_members", "joined_members"
        )
        joined = answer.get("joined")
        return frozenset(joined) if isinstance(joined, Mapping) else frozenset()

    async def _call(
        self,
        method: str,
        path: str,
        endpoint: str,
        *,
        params: Mapping[str, str | int] | None = None,
        json: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        response = await self._http.request(method, path, params=params, json=json)
        try:
            answer = response.json()
        except ValueError:
            answer = {}
        if not isinstance(answer, Mapping):
            answer = {}
        if response.is_success:
            return answer
        errcode = answer.get("errcode")
        retry_after = answer.get("retry_after_ms")
        raise MatrixError(
            endpoint,
            response.status_code,
            errcode if isinstance(errcode, str) else None,
            retry_after if isinstance(retry_after, int) else _retry_after_header(response),
        )


def _retry_after_header(response: httpx.Response) -> int | None:
    value = response.headers.get("retry-after", "")
    return int(value) * 1000 if value.isdigit() else None
