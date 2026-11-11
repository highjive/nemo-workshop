"""Routing between the local model and a remote API.

Stdlib only. On a 2-core Sandy Bridge machine, every avoidable dependency
is a pip install that takes minutes, so this speaks HTTP with urllib.

The routing table in config decides which brain handles which task. When the
network is gone, remote tasks fall back to local and the caller is told, so
stages can ask the user more questions instead of guessing.
"""

from __future__ import annotations

import json
import os
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .config import LOCAL, LOCAL_THEN_REVIEW, REMOTE, Config


class RouterError(RuntimeError):
    pass


# Every way a call can fail for reasons outside this process.
_NETWORK = (RouterError, urllib.error.URLError, socket.timeout, OSError)


@dataclass
class Reply:
    text: str
    source: str          # "local", "remote", or "archive" (the Archivist's)
    model: str
    degraded: bool = False   # remote was wanted but unreachable
    queued: str = ""          # review request id, if saved for later


def _post(url: str, payload: dict, key: str | None, timeout: int) -> dict:
    body = json.dumps(payload).encode()
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    req = urllib.request.Request(url, data=body, headers=headers,
                                 method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


class ModelCallFailed(RuntimeError):
    """The model could not be asked, or did not answer. Its message is for
    the person at the screen, not for a log."""


def explain_failure(exc: BaseException, timeout: int) -> str | None:
    """A plain sentence for a failed model call, or None if `exc` is not one.

    D125, from the first real pipeline run on the AH531: the electrical step
    asked the model for a schematic, the model was still writing when the
    900 s limit passed, and the run ended in a sixty-line traceback ending
    `TimeoutError: timed out`. No step result was saved and nothing said
    what had happened or what to do.
    """
    reason = getattr(exc, "reason", None)
    if isinstance(exc, (TimeoutError, socket.timeout)) or \
            isinstance(reason, (TimeoutError, socket.timeout)):
        return (f"The model had not finished after {timeout} s, which is the limit "
                "(engine.timeout_s in config.yaml). Nothing was written for this "
                "step. On a slow machine a long reply can simply take longer than "
                "that: raise the limit, or use a smaller mode (nemo mode talk).")
    if isinstance(exc, RouterError):
        return f"The model call could not be made: {exc}"
    if isinstance(exc, urllib.error.HTTPError):
        # D177, the AH531 on 2026-10-16: llama-server answered step 3 with
        # 400 Bad Request, and this said the model had "stopped answering
        # part way through", which it had not: it refused the request at
        # once, and said why in the body this threw away.
        said = _server_said(exc)
        return (f"The language model server refused the request (HTTP {exc.code} "
                f"{exc.reason}). It said: {said or 'nothing'}. The model is "
                "loaded; it is the question it would not take. Nothing was "
                "written for this step.")
    # Refused outright: nothing is listening, so no model is loaded at all. It
    # was said to have "stopped answering part way through", which it never
    # began (2026-11-04: the Concept step run with no mode loaded).
    if isinstance(exc, ConnectionRefusedError) or isinstance(reason, ConnectionRefusedError):
        return ("No language model is loaded: nothing answers at the model's address "
                f"({reason or exc}). Load one with the Model box at the top, or: nemo mode design")
    if isinstance(exc, (urllib.error.URLError, ConnectionError)):
        return ("The language model stopped answering part way through "
                f"({reason or exc}). Check it is still loaded with: nemo mode")
    return None


def _server_said(exc) -> str:
    """The reason an HTTP error's body gives: llama-server's
    {"error": {"message": ...}}, or the first of its text."""
    try:
        raw = exc.read().decode("utf-8", "replace")
    except Exception:                                      # noqa: BLE001
        return ""
    try:
        err = json.loads(raw).get("error")
        msg = err.get("message") if isinstance(err, dict) else err
        if msg:
            return str(msg)[:500]
    except (ValueError, AttributeError):
        pass
    return raw.strip()[:500]


def _content(resp: dict) -> str:
    try:
        return resp["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as exc:
        raise RouterError(f"unexpected response shape: {resp}") from exc


class Router:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.timeout = int(cfg.get("engine.timeout_s", 900))

    # --- availability -------------------------------------------------

    def local_up(self) -> bool:
        base = self.cfg.get("engine.local")
        try:
            urllib.request.urlopen(f"{base}/models", timeout=3)
            return True
        except (urllib.error.URLError, socket.timeout, OSError):
            return False

    def online(self) -> bool:
        try:
            socket.create_connection(("1.1.1.1", 53), timeout=3).close()
            return True
        except OSError:
            return False

    # --- calls --------------------------------------------------------

    # The local server can hold a reply to a JSON schema; a remote reviewer
    # is not asked to.
    supports_schema = True

    def _call_local(self, messages, temperature, max_tokens, task=None,
                    schema=None) -> Reply:
        model = self.cfg.get("engine.local_model", "local")
        payload = {"model": model, "messages": messages,
                   "temperature": temperature, "max_tokens": max_tokens}
        # D119: Qwen3 reasons out loud before it answers unless told not to,
        # and that reasoning is counted against max_tokens. See
        # engine.thinking_off in config.py for what that did to story mode.
        if task in (self.cfg.get("engine.thinking_off") or []):
            payload["chat_template_kwargs"] = {"enable_thinking": False}
        if schema is not None:
            # llama-server turns this into a grammar: a token that would
            # break the schema cannot be produced at all.
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "reply", "schema": schema}}
        # The Archivist (nemo/archivist.py): the identical request to the
        # identical model, answered before in a step that passed, is not
        # asked again. The step's checks still judge the answer.
        from . import archivist, modes
        loaded = modes.current().model
        akey = archivist.key(payload, loaded)
        if archivist.on(self.cfg):
            kept = archivist.recall(akey)
            if kept is not None:
                self.cache_note = "the Archivist had this answer"
                return Reply(kept, "archive", model)
        self.cache_note = self._warm_cache(messages, payload)
        try:
            resp = _post(f"{self.cfg.get('engine.local')}/chat/completions",
                         payload, None, self.timeout)
        except urllib.error.HTTPError:
            # D177: keep what was refused, so it can be looked at and sent
            # to the server again by hand. The brief's own words are in it,
            # and it stays in this machine's ~/.nemo.
            try:
                home = Path(os.environ.get("NEMO_HOME", Path.home() / ".nemo"))
                home.mkdir(parents=True, exist_ok=True)
                (home / "refused-request.json").write_text(
                    json.dumps(payload, indent=1), encoding="utf-8")
            except OSError:
                pass
            raise
        text = _content(resp)
        if archivist.on(self.cfg):
            archivist.note(akey, text, task)
        return Reply(text, "local", model)

    def _warm_cache(self, messages, payload) -> str:
        """Have the server start from its saved reading of this system
        prompt (nemo/slotcache.py). Only for a server modes.start began,
        which is the one that was given a folder to keep it in."""
        if not self.cfg.get("engine.prompt_cache", True):
            return "off: engine.prompt_cache is false"
        if not messages or messages[0].get("role") != "system":
            return "off: no system prompt"
        from . import modes, slotcache
        state = slotcache.read_state(modes.STATE.parent)
        st = modes.current()
        if state is None or not st.running or state[0] != st.pid:
            return "off: the server was not started with a cache folder"
        return slotcache.prepare(self.cfg.get("engine.local"), st.pid, state[1],
                                 messages[0]["content"], payload, self.timeout,
                                 stick=state[2])

    def _call_remote(self, messages, temperature, max_tokens) -> Reply:
        spec = self.cfg.get("engine.review")
        if not spec:
            raise RouterError("no remote model configured (engine.review)")
        provider = spec.split("/", 1)[0]
        model = spec.split("/", 1)[1] if "/" in spec else spec
        key = Config.api_key(provider)
        if not key:
            raise RouterError(
                f"no API key in environment for {provider!r}; "
                f"export NEMO_{provider.upper()}_KEY"
            )
        resp = _post(
            f"{self.cfg.get('engine.review_base')}/chat/completions",
            {"model": model, "messages": messages,
             "temperature": temperature, "max_tokens": max_tokens},
            key, self.timeout,
        )
        return Reply(_content(resp), "remote", model)

    def ask(self, task: str, system: str, user: str,
            temperature: float = 0.2, max_tokens: int = 2048,
            schema: dict | None = None) -> Reply:
        """Run one exchange, routed by task name.

        `schema` constrains the LOCAL model's reply to a JSON schema. A
        schema'd task is one whose answer plain code will read, so it is
        answered locally whatever its route says: a reviewer rewriting it
        in prose would defeat the point.
        """
        if schema is not None:
            messages = [{"role": "system", "content": system},
                        {"role": "user", "content": user}]
            return self._call_local(messages, temperature, max_tokens, task, schema)
        route = self.cfg.route_for(task)
        messages = [{"role": "system", "content": system},
                    {"role": "user", "content": user}]

        offline_ok = self.cfg.get("routing.offline") == "degrade_to_local"

        if route == LOCAL:
            return self._call_local(messages, temperature, max_tokens, task)

        if route == REMOTE:
            try:
                return self._call_remote(messages, temperature, max_tokens)
            except _NETWORK:
                if not offline_ok:
                    raise
                reply = self._call_local(messages, temperature, max_tokens, task)
                reply.degraded = True
                return reply

        if route == LOCAL_THEN_REVIEW:
            # Draft locally, then send the draft out for review. Exactly one
            # remote call. An earlier revision called remote first, discarded
            # the answer, then called it again for the review -- doubling the
            # cost and the latency of every CAD and firmware stage.
            draft = self._call_local(messages, temperature, max_tokens, task)
            try:
                return self.review(task, system, user, draft.text)
            except _NETWORK:
                draft.degraded = True
                # Offline: keep the request rather than dropping it, if a
                # reviewer is configured to send it to later.
                if self.cfg.get("engine.review"):
                    from .reviews import enqueue
                    draft.queued = enqueue(task, system, user, draft.text,
                                           getattr(self, "context", None))
                return draft

        raise RouterError(f"unknown route {route!r} for task {task!r}")

    def review(self, task: str, system: str, user: str, draft: str) -> Reply:
        """Second opinion on a draft. Asks for contradictions, not praise."""
        scope = self.cfg.get("checks.tier2.scope",
                             "contradictions|failure_modes")
        prompt = (
            "Below is a brief and a draft produced by a small local model.\n"
            f"Review it for: {scope.replace('|', ', ')}.\n"
            "Do not compliment the draft. Do not restate it. Either return "
            "a corrected version, or return the draft unchanged with a short "
            "list of concrete problems.\n\n"
            f"--- BRIEF ---\n{user}\n\n--- DRAFT ---\n{draft}\n"
        )
        return self._call_remote(
            [{"role": "system", "content": system},
             {"role": "user", "content": prompt}], 0.1, 2048)
