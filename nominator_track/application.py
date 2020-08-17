import asyncio
import difflib
import json
import os
import signal
import sys
import traceback
from typing import Dict, List

from appdirs import AppDirs
from authlib.integrations.httpx_client import AsyncOAuth2Client
from pyee import AsyncIOEventEmitter

from nominator_track.web import get_group_members, get_user_bbcode


class NominatorTrack:
    _oauth_scope = "identify public"
    _authorization_endpoint = "https://osu.ppy.sh/oauth/authorize"
    _token_endpoint = "https://osu.ppy.sh/oauth/token"
    _closed = False
    _dirs = AppDirs("NominatorTrack", "Keitaro")

    members: Dict[str, List[int]] = {"probation": [], "full": []}
    members_bbcode: Dict[str, Dict[int, str]] = {"probation": {}, "full": {}}

    def __init__(
        self,
        client_id,
        client_secret,
        loop=None,
        token=None,
        token_file=None,
        emitter=None,
        handlers=None,
    ):
        if not token_file:
            os.makedirs(self._dirs.user_config_dir, exist_ok=True)
            token_file = self._dirs.user_config_dir + "/token.json"

        if os.path.exists(token_file):
            with open(token_file, "r") as f:
                token = json.load(f)

        self.tasks = []
        self.loop = loop or asyncio.get_event_loop()
        self.web_client = AsyncOAuth2Client(
            client_id, client_secret, scope=self._oauth_scope
        )

        if not token:
            from nominator_track.utils import get_refresh_token

            self.token = self.loop.run_until_complete(
                get_refresh_token(
                    self.web_client,
                    self._authorization_endpoint,
                    self._token_endpoint,
                    body=f"client_id={client_id}&client_secret={client_secret}&redirect_uri=http://127.0.0.1:8080/",
                )
            )
        else:
            self.token = token
        self.web_client.token = self.token

        with open(token_file, "w") as f:
            json.dump(self.token, f)

        self.loop.run_until_complete(self._get_members())

        self.emitter = emitter or AsyncIOEventEmitter()
        self.handlers = handlers
        if handlers:
            for handler in handlers:
                handler.register_emitter(self.emitter)
                handler.app = self

    async def on_error(self, error):
        print("An error occured, will keep running anyway.", file=sys.stderr)
        traceback.print_exception(
            type(error), error, error.__traceback__, file=sys.stderr
        )

    async def _get_members(self):
        probation_members = await get_group_members(32)
        full_members = await get_group_members(28)

        for member in probation_members:
            self.members["probation"].append(member)
        for member in full_members:
            self.members["full"].append(member)

    async def _get_difference(self, user, member_type):
        uid = user["id"]
        bbcode = await get_user_bbcode(self.web_client, uid)
        if uid not in self.members_bbcode[member_type]:
            self.members_bbcode[member_type][uid] = bbcode
            return

        original = self.members_bbcode[member_type][uid]
        if original == bbcode:
            return

        self.members_bbcode[member_type][uid] = bbcode
        difference = difflib.unified_diff(
            original.splitlines(),
            bbcode.splitlines(),
            fromfile="before",
            tofile="after",
        )
        self.emitter.emit("change", user, difference)
        return difference

    async def check_members(self):
        while not self._closed:
            try:
                for user in self.members["probation"]:
                    diff = await self._get_difference(user, "probation")
                    if diff:
                        self.emitter.emit("probation_change", user, diff)

                for user in self.members["full"]:
                    diff = await self._get_difference(user, "full")
                    if diff:
                        self.emitter.emit("full_change", user, diff)

            except Exception as e:
                await self.on_error(e)

            await asyncio.sleep(1 * 60)

    async def sync_members(self):
        while not self._closed:
            try:
                await self._get_members()
            except Exception as e:
                await self.on_error(e)

            await asyncio.sleep(30 * 60)

    def add_handler(self, handler):
        handler.register_emitter(self.emitter)

    def start(self):
        if not self.handlers:
            raise Exception("Requires at least one Handler.")

        self.tasks.append(self.loop.create_task(self.sync_members()))
        self.tasks.append(self.loop.create_task(self.check_members()))

    def run(self):
        async def _stop():
            self._closed = True
            for t in self.tasks:
                t.cancel()

            asyncio.gather(*self.tasks, return_exceptions=True)
            self.loop.stop()
            self.loop.close()

        def stop():
            asyncio.ensure_future(_stop())

        try:
            self.loop.add_signal_handler(signal.SIGINT, stop)
            self.loop.add_signal_handler(signal.SIGTERM, stop)
        except NotImplementedError:
            pass

        try:
            self.start()
            self.loop.run_forever()
        except KeyboardInterrupt:
            print("Exiting...")
        finally:
            stop()
