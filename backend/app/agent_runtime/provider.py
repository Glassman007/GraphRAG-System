"""Strict OpenAI-compatible chat-completions adapter: OpenAI, Groq, configured endpoint.

The agent only receives graph facts after the caller explicitly consents to transmission.
Provider responses are untrusted, validated in the harness, and never executed as code.
"""
from __future__ import annotations

import os
import time
import json
import hashlib
import math
import re
import threading
from collections import deque
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx


class ProviderError(RuntimeError):
    pass


class ProviderRateLimited(ProviderError):
    """Explicit rate-limit result, never an indication of graph corruption."""

    def __init__(self, detail: str, retry_after: float | None = None):
        super().__init__(detail)
        self.retry_after = retry_after


def _duration(value: str) -> float | None:
    """Parse Groq durations such as 7.66s or 2m59.56s, without guessing."""
    value = value.strip()
    try:
        return max(0.0, float(value)) if value else None
    except ValueError:
        pass
    matches = list(re.finditer(r'(\d+(?:\.\d+)?)(h|m|s)', value))
    if not matches or ''.join(m.group(0) for m in matches) != value:
        return None
    return sum(float(m.group(1)) * {'h':3600,'m':60,'s':1}[m.group(2)] for m in matches)


class TokenPacer:
    """Conservative in-process sliding-window reservation + provider-header pacing.

    This limits requests issued by this Python process. It cannot reserve tokens
    used by other machines/processes in the same Groq organization; HTTP response
    headers and 429 handling are therefore still authoritative.
    """

    def __init__(self, capacity: int):
        self.capacity = capacity
        self.lock = threading.Lock()
        self.records = deque()  # list of [timestamp, projected/actual charged tokens, token]
        self.remote_remaining: int | None = None
        self.remote_until = 0.0

    def reserve(self, cost: int, available_seconds: float) -> list:
        if cost > self.capacity:
            raise ProviderRateLimited('Groq projected request exceeds per-minute safety budget; reduce context or output', 60.0)
        start = time.monotonic()
        deadline = start + max(0.0, available_seconds - 3.0)
        with self.lock:
            while True:
                now = time.monotonic()
                while self.records and now - self.records[0][0] >= 60:
                    self.records.popleft()
                local = sum(row[1] for row in self.records)
                local_wait = self.records[0][0] + 60 - now if local + cost > self.capacity and self.records else 0
                remote_wait = (self.remote_until - now if self.remote_remaining is not None
                               and self.remote_remaining < cost and self.remote_until > now else 0)
                delay = max(0.0, local_wait, remote_wait)
                if delay <= 0:
                    token = [now, cost, object()]
                    self.records.append(token)
                    if self.remote_remaining is not None and now < self.remote_until:
                        self.remote_remaining = max(0, self.remote_remaining - cost)
                    return token
                if now + delay > deadline:
                    raise ProviderRateLimited('Groq TPM pacing would exceed the remaining agent deadline; wait and retry later', round(delay, 1))
                time.sleep(delay + 0.02)

    def defer(self, retry_after: float | None) -> None:
        if retry_after is None:
            return
        with self.lock:
            self.remote_remaining = 0
            self.remote_until = max(self.remote_until, time.monotonic() + retry_after)

    def settle(self, ticket: list, actual: int, headers: Any = None) -> None:
        with self.lock:
            ticket[1] = max(0, actual)
            if headers is not None:
                try:
                    remaining = int(headers.get('x-ratelimit-remaining-tokens'))
                except (ValueError, TypeError):
                    remaining = None
                reset = _duration(headers.get('x-ratelimit-reset-tokens', ''))
                if remaining is not None and reset is not None:
                    self.remote_remaining = max(0, remaining)
                    self.remote_until = time.monotonic() + reset


_PACERS: dict[tuple[str, str], TokenPacer] = {}
_PACERS_LOCK = threading.Lock()


def _pacer(model: str, api_key: str) -> TokenPacer:
    # Key hash prevents mixing unrelated accounts, without retaining raw key.
    key = (model, hashlib.sha256(api_key.encode()).hexdigest())
    with _PACERS_LOCK:
        if key not in _PACERS:
            # User-confirmed free-plan limit is 8K TPM. Reserve 10% headroom.
            maximum = int(os.getenv('GRAPH_HACKS_GROQ_TPM', '8000'))
            if not 500 <= maximum <= 1000000:
                raise ProviderError('GRAPH_HACKS_GROQ_TPM must be between 500 and 1000000')
            _PACERS[key] = TokenPacer(int(maximum * 0.9))
        return _PACERS[key]


@dataclass(frozen=True)
class Completion:
    content: str
    calls: list[dict[str, Any]]
    tokens: int
    finish_reason: str = ""


class OpenAICompatibleProvider:
    def __init__(self, *, provider: str | None = None):
        name = (provider or os.getenv('GRAPH_HACKS_AGENT_PROVIDER') or 'groq').strip().lower()
        if name not in {'groq', 'openai', 'compatible'}:
            raise ProviderError('Agent provider must be groq, openai, or compatible')
        bases = {'groq': 'https://api.groq.com/openai/v1', 'openai': 'https://api.openai.com/v1'}
        models = {'groq': 'openai/gpt-oss-120b', 'openai': 'gpt-4.1-mini'}
        base = bases.get(name) or os.getenv('GRAPH_HACKS_AGENT_BASE_URL', '').strip().rstrip('/')
        parsed = urlparse(base)
        if not base or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path.endswith('/chat/completions'):
            raise ProviderError('Invalid provider base URL')
        if parsed.scheme != 'https' and not (parsed.scheme == 'http' and parsed.hostname in {'127.0.0.1', 'localhost'}):
            raise ProviderError('Provider endpoints must use HTTPS, except local loopback')
        if name != 'compatible' and base != bases[name]:
            raise ProviderError('Built-in provider endpoint cannot be overridden')
        env_key = {'groq':'GROQ_API_KEY', 'openai':'OPENAI_API_KEY','compatible':'GRAPH_HACKS_AGENT_API_KEY'}[name]
        self.api_key = os.getenv(env_key, '').strip()
        if name != 'compatible' and not self.api_key:
            raise ProviderError(f'{env_key} is missing; no model call was made')
        self.name = name
        self.base = base
        self.model = os.getenv('GRAPH_HACKS_AGENT_MODEL', models.get(name, '')).strip()
        if not self.model:
            raise ProviderError('Set GRAPH_HACKS_AGENT_MODEL')

    def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]], *,
                 remaining_seconds: float, max_output_tokens: int) -> Completion:
        if remaining_seconds <= 0:
            raise ProviderError('Agent deadline reached')
        headers = {'Content-Type': 'application/json'}
        if self.api_key:
            headers['Authorization'] = 'Bearer ' + self.api_key
        payload: dict[str, Any] = {
            'model': self.model, 'messages': messages, 'temperature': 0,
            'max_completion_tokens': max_output_tokens,
        }
        if tools:
            payload['tools'] = tools
            payload['tool_choice'] = 'auto'
        elif self.name == 'groq':
            # Planning has no tool calls and must return parseable JSON.
            # Do not apply JSON mode to tool calls; those require function messages.
            payload['response_format'] = {'type': 'json_object'}
        if self.name == 'groq' and self.model in {'openai/gpt-oss-120b', 'openai/gpt-oss-20b'}:
            # GPT-OSS counts internal reasoning against output/rate budgets.
            payload['reasoning_effort'] = 'low'
            if tools:
                payload['parallel_tool_calls'] = False
        ticket = None
        pacer = None
        started = time.monotonic()
        try:
            if self.name == 'groq':
                pacer = _pacer(self.model, self.api_key)
                # Estimate input conservatively; reserve full output capacity.
                # This is NOT a tokenizer and cannot guarantee an organization-wide limit.
                prompt_estimate = math.ceil((len(json.dumps(messages, default=str)) +
                    len(json.dumps(tools, default=str))) / 3.1)
                ticket = pacer.reserve(prompt_estimate + max_output_tokens, remaining_seconds)
            with httpx.Client(timeout=min(max(0.5, remaining_seconds - (time.monotonic()-started)), 25.0),
                              follow_redirects=False) as client:
                for attempt in range(2):
                    response = client.post(f'{self.base}/chat/completions', json=payload, headers=headers)
                    if response.status_code != 429:
                        break
                    retry_header = response.headers.get('retry-after', '')
                    delay = _duration(retry_header)
                    time_left = remaining_seconds - (time.monotonic() - started)
                    if attempt == 0 and delay is not None and 0 <= delay <= min(65.0, time_left - 3):
                        time.sleep(delay + 0.15)
                        continue
                    if pacer is not None:
                        pacer.defer(delay)
                    hint = f'; retry-after={retry_header}s' if retry_header else '; inspect Groq organization quota'
                    raise ProviderRateLimited(f'{self.name} rate limited (HTTP 429){hint}', delay)
            if response.status_code != 200:
                raise ProviderError(f'{self.name} returned HTTP {response.status_code}')
            body = response.json()
            choice = body['choices'][0]
            message = choice['message']
            calls = []
            for call in message.get('tool_calls') or []:
                function = call.get('function') or {}
                calls.append({'id': str(call.get('id') or ''), 'name': str(function.get('name') or ''),
                              'arguments': str(function.get('arguments') or '{}')})
            usage = int((body.get('usage') or {}).get('total_tokens') or 0)
            if pacer is not None and ticket is not None:
                pacer.settle(ticket, usage or ticket[1], response.headers)
                ticket = None
            return Completion(content=str(message.get('content') or ''), calls=calls,
                              tokens=usage,
                              finish_reason=str(choice.get('finish_reason') or ''))
        except ProviderError:
            raise
        except (httpx.RequestError, ValueError, KeyError, TypeError, IndexError) as exc:
            raise ProviderError(f'{self.name} request or response failed: {type(exc).__name__}') from None
        finally:
            if pacer is not None and ticket is not None:
                # Errors may still consume provider tokens, but avoid reserving the
                # full unspent output allowance for failed requests.
                pacer.settle(ticket, 0)
