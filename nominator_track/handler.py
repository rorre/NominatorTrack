import asyncio
import json
from typing import Iterator
from urllib.parse import quote

import discord
import httpx
from discord import utils
from discord.errors import Forbidden, HTTPException, NotFound
from discord.webhook import WebhookAdapter


class Handler:
    def __init__(self):
        self.app = None

    def register_emitter(self, emitter):
        self.emitter = emitter
        self._register_events()

    def _register_events(self):
        for func in dir(self):
            if not func.startswith("on_"):
                continue
            self.emitter.on("_".join(func.split("_")[1:]), getattr(self, func))


class DiscordHandler(Handler):
    _position = {"bng": "Full BN", "bng_limited": "Probation BN"}

    def __init__(self, webhook_url):
        self.webhook_url = webhook_url
        super().__init__()

    def _create_embed(self, user, difference):
        _title = ":warning: A nominator changed their userpage!"
        _colour = discord.Colour(0x4A90E2)
        _url = f"https://osu.ppy.sh/u/{user['id']}"
        _diff_text = "\r\n".join(list(difference))

        if len(_diff_text) > 2000:
            _desc = f"Difference too big. [You can look it yourself]({_url})."
        else:
            _desc = f"```{_diff_text}```"
        embed = discord.Embed(title=_title, colour=_colour, url=_url, description=_desc)

        embed.set_thumbnail(url=f"http://s.ppy.sh/a/{user['id']}")
        embed.set_footer(
            text=f"{user['username']} | {self._position.get(user['default_group'])}"
        )

        return embed

    async def on_change(self, user, difference: Iterator[str]):
        embed = self._create_embed(user, difference)
        webhook = discord.Webhook.from_url(
            self.webhook_url, adapter=HTTPXWebhookAdapter()
        )
        await webhook.send(embed=embed)


# Below is the same exact code as RequestsWebhookAdapter
# but adapted to async.
# https://github.com/Rapptz/discord.py/blob/master/discord/webhook.py
class HTTPXWebhookAdapter(WebhookAdapter):
    def __init__(self, session=None):
        self.session = session or httpx.AsyncClient()

    async def request(
        self, verb, url, payload=None, multipart=None, *, files=None, reason=None
    ):
        headers = {}
        data = None
        files = files or []
        if payload:
            headers["Content-Type"] = "application/json"
            data = utils.to_json(payload)

        if reason:
            headers["X-Audit-Log-Reason"] = quote(reason, safe="/ ")

        if multipart is not None:
            data = {"payload_json": multipart.pop("payload_json")}

        for tries in range(5):
            for file in files:
                file.reset(seek=tries)

            r = await self.session.request(
                verb, url, headers=headers, data=data, files=multipart
            )
            r.encoding = "utf-8"
            # Coerce empty responses to return None for hygiene purposes
            response = r.text or None

            # compatibility with aiohttp
            r.status = r.status_code

            if r.headers["Content-Type"] == "application/json":
                response = json.loads(response)

            # check if we have rate limit header information
            remaining = r.headers.get("X-Ratelimit-Remaining")
            if remaining == "0" and r.status != 429:
                delta = utils._parse_ratelimit_header(r)
                await asyncio.sleep(delta)

            if 300 > r.status >= 200:
                return response

            # we are being rate limited
            if r.status == 429:
                if self.sleep:
                    retry_after = response["retry_after"] / 1000.0
                    await asyncio.sleep(retry_after)
                    continue
                else:
                    raise HTTPException(r, response)

            if self.sleep and r.status in (500, 502):
                await asyncio.sleep(1 + tries * 2)
                continue

            if r.status == 403:
                raise Forbidden(r, response)
            elif r.status == 404:
                raise NotFound(r, response)
            else:
                raise HTTPException(r, response)
        # no more retries
        raise HTTPException(r, response)

    def handle_execution_response(self, response, *, wait):
        if not wait:
            return response

        # transform into Message object
        from discord.message import Message

        return Message(
            data=response, state=self.webhook._state, channel=self.webhook.channel
        )
