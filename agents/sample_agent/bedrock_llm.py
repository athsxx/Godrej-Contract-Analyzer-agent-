"""Optional Bedrock LLM client (disabled unless explicitly enabled)."""

from __future__ import annotations

import json
import logging
from typing import List, Optional

from . import config as agent_config

logger = logging.getLogger(__name__)

_bedrock_client = None


def _get_bedrock_client():
    global _bedrock_client
    if _bedrock_client is not None:
        return _bedrock_client
    try:
        import boto3
    except Exception as e:
        raise RuntimeError("boto3 is required for Bedrock provider.") from e

    _bedrock_client = boto3.client(
        "bedrock-runtime",
        region_name=agent_config.AWS_REGION,
        aws_access_key_id=agent_config.AWS_ACCESS_KEY_ID or None,
        aws_secret_access_key=agent_config.AWS_SECRET_ACCESS_KEY or None,
    )
    return _bedrock_client


def call_bedrock_chat(
    prompt: str,
    *,
    system_message: str | None = None,
    model_id: str | None = None,
    temperature: float | None = None,
    top_p: float | None = None,
    max_tokens: int | None = None,
    image_bytes: Optional[List[bytes]] = None,
) -> str:
    """Call Bedrock chat APIs with converse-first and invoke_model fallback."""
    if not agent_config.ENABLE_BEDROCK:
        raise RuntimeError("Bedrock path is disabled. Set ENABLE_BEDROCK=1 to enable.")

    model = model_id or agent_config.BEDROCK_MODEL_ID
    if not model:
        raise RuntimeError("BEDROCK_MODEL_ID must be set for Bedrock provider.")

    temp = float(agent_config.LOCAL_LLM_TEMPERATURE if temperature is None else temperature)
    tp = float(agent_config.LOCAL_LLM_TOP_P if top_p is None else top_p)
    max_tok = int(agent_config.LOCAL_LLM_MAX_TOKENS if max_tokens is None else max_tokens)

    client = _get_bedrock_client()
    images = []
    for blob in image_bytes or []:
        try:
            images.append({"image": {"format": "png", "source": {"bytes": blob}}})
        except Exception:
            continue

    # Bedrock converse path.
    try:
        messages = [{"role": "user", "content": [{"text": prompt}, *images]}]
        system_blocks = [{"text": system_message}] if system_message else []
        resp = client.converse(
            modelId=model,
            messages=messages,
            inferenceConfig={"temperature": temp, "topP": tp, "maxTokens": max_tok},
            system=system_blocks or None,
        )
        parts = resp.get("output", {}).get("message", {}).get("content", []) or []
        text = "".join(p.get("text", "") for p in parts if isinstance(p, dict))
        if text.strip():
            return text.strip()
    except Exception as err:
        last_error: Exception | None = err
        if agent_config.DEBUG_AGENT:
            logger.warning("Bedrock converse failed: %s", err)
    else:
        last_error = None

    # Fallback: invoke_model path.
    body = {
        "prompt": f"[System]\n{system_message}\n\n[User]\n{prompt}" if system_message else prompt,
        "max_tokens_to_sample": max_tok,
        "temperature": temp,
        "top_p": tp,
    }
    try:
        resp = client.invoke_model(
            modelId=model,
            contentType="application/json",
            accept="application/json",
            body=json.dumps(body),
        )
        data = json.loads(resp["body"].read().decode("utf-8"))
        if isinstance(data, dict):
            if data.get("generation"):
                return str(data["generation"]).strip()
            if data.get("outputs"):
                return str(data["outputs"][0].get("text", "")).strip()
            if data.get("output_text"):
                return str(data["output_text"]).strip()
    except Exception as err:
        last_error = last_error or err

    raise last_error or RuntimeError("Bedrock returned an empty response.")

