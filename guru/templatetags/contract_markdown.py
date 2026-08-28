"""Render Agent 2 markdown (tables, headings) to safe HTML for the workspace."""

from __future__ import annotations

import bleach
import markdown
from django import template
from django.utils.safestring import mark_safe

register = template.Library()

_ALLOWED_TAGS = [
    "p",
    "br",
    "strong",
    "em",
    "code",
    "pre",
    "ul",
    "ol",
    "li",
    "h1",
    "h2",
    "h3",
    "h4",
    "blockquote",
    "hr",
    "table",
    "thead",
    "tbody",
    "tr",
    "th",
    "td",
    "a",
]

_ALLOWED_ATTRS = {
    "a": ["href", "rel", "title"],
    "th": ["colspan", "rowspan", "align"],
    "td": ["colspan", "rowspan", "align"],
}


@register.filter(name="contract_markdown")
def contract_markdown(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    try:
        html_out = markdown.markdown(
            raw,
            extensions=["tables", "nl2br", "fenced_code"],
            output_format="html",
        )
    except Exception:
        from django.utils.html import escape

        return mark_safe(f'<pre class="risk-md-fallback">{escape(raw)}</pre>')

    clean = bleach.clean(
        html_out,
        tags=_ALLOWED_TAGS,
        attributes=_ALLOWED_ATTRS,
        strip=True,
    )
    return mark_safe(f'<div class="risk-md-rendered">{clean}</div>')
