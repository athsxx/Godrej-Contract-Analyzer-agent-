"""Local LLM client (Ollama-compatible). No AWS."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from . import config as agent_config

logger = logging.getLogger(__name__)
if agent_config.DEBUG_AGENT:
    logging.basicConfig(level=logging.DEBUG)


def _preview(text: str | None, limit: int = 240) -> str:
    if not text:
        return ""
    compact = " ".join(str(text).split())
    if len(compact) <= limit:
        return compact
    return compact[:limit] + "..."


def call_local_chat(
    prompt: str,
    *,
    system_message: str | None = None,
    model_id: str | None = None,
    temperature: float | None = None,
    top_p: float | None = None,
    max_tokens: int | None = None,
    image_bytes: Optional[List[bytes]] = None,
) -> str:
    """
    Call local LLM (Ollama-compatible API). Same contract as the previous
    call_bedrock_chat for drop-in replacement. image_bytes is ignored for
    this client (Ollama chat API supports images only in certain models;
    we keep the signature for compatibility).
    """
    model = model_id or agent_config.LOCAL_LLM_MODEL
    base_url = agent_config.LOCAL_LLM_BASE_URL
    if not base_url or not model:
        raise RuntimeError("LOCAL_LLM_BASE_URL and LOCAL_LLM_MODEL must be set (e.g. via env).")

    temp = float(temperature if temperature is not None else agent_config.LOCAL_LLM_TEMPERATURE)
    top_p_val = float(top_p if top_p is not None else agent_config.LOCAL_LLM_TOP_P)
    max_tok = int(max_tokens if max_tokens is not None else agent_config.LOCAL_LLM_MAX_TOKENS)

    messages: List[Dict[str, Any]] = []
    if system_message:
        messages.append({"role": "system", "content": system_message})
    messages.append({"role": "user", "content": prompt})

    body = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {
            "temperature": temp,
            "top_p": top_p_val,
            "num_predict": max_tok,
        },
    }

    url = f"{base_url}/api/chat"
    if agent_config.DEBUG_AGENT:
        logger.info(
            "LLM request: model=%s base_url=%s prompt_chars=%d system_chars=%d temp=%.3f top_p=%.3f max_tokens=%d images=%d",
            model,
            base_url,
            len(prompt or ""),
            len(system_message or ""),
            temp,
            top_p_val,
            max_tok,
            len(image_bytes or []),
        )
        logger.debug("LLM prompt preview: %s", _preview(prompt))

    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body_err = e.read().decode("utf-8", errors="replace") if e.fp else ""
        if agent_config.DEBUG_AGENT:
            logger.error("LLM HTTPError: code=%s reason=%s body=%s", e.code, e.reason, _preview(body_err))
        raise RuntimeError(f"Local LLM request failed: {e.code} {e.reason}. {body_err}") from e
    except urllib.error.URLError as e:
        if agent_config.DEBUG_AGENT:
            logger.error("LLM URLError: base_url=%s reason=%s", base_url, e.reason)
        raise RuntimeError(f"Local LLM unreachable at {base_url}. Is Ollama running? {e.reason}") from e

    content = (data.get("message") or {}).get("content") if isinstance(data, dict) else None
    if content is None:
        if agent_config.DEBUG_AGENT:
            logger.error("LLM empty response payload: %s", _preview(str(data)))
        raise RuntimeError("Local LLM returned an empty response.")
    if agent_config.DEBUG_AGENT:
        logger.info("LLM response: chars=%d", len(str(content)))
        logger.debug("LLM response preview: %s", _preview(str(content)))
    return str(content).strip()
