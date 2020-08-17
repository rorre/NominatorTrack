import json
from typing import Any, Dict, List, Union

import httpx
from authlib.integrations.httpx_client import AsyncOAuth2Client
from bs4 import BeautifulSoup


async def _fetch_web(url: str) -> BeautifulSoup:
    """Fetches url from the web."""
    async with httpx.AsyncClient() as client:
        r = await client.get(url)
        r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser")


async def get_group_members(gid: Union[int, str]) -> List[Dict[str, Any]]:
    soup = await _fetch_web(f"https://osu.ppy.sh/groups/{gid}")
    json_users_select = soup.select("#json-users")
    if not json_users_select:
        raise AttributeError(
            "No json-users id found. Maybe cloudflare or endpoint has changed."
        )
    return json.loads(json_users_select[0].string)


async def get_user_bbcode(client: AsyncOAuth2Client, uid: Union[int, str]) -> str:
    r = await client.get(f"https://osu.ppy.sh/api/v2/users/{uid}")
    r.raise_for_status()

    user_json = r.json()
    return user_json["page"]["raw"]
