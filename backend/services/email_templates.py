"""Turns an email's paragraphs and optional link into a plain-text body and a simple
HTML body. Kept separate from NotificationService so the wording stays in one place
and the layout in another.

The HTML is deliberately plain: inline styles only, no images and nothing loaded from
elsewhere, so mail apps show it as sent and nothing tracks the reader. Every value is
HTML-escaped here, so a name such as "<b>Pat</b>" arrives as text, not markup.
"""
from html import escape
from typing import NamedTuple, Optional, Sequence

_FONT = "font-family:Arial,Helvetica,sans-serif;color:#1f2937;"


class EmailContent(NamedTuple):
    subject: str
    text: str
    html: str


def render_email(
    subject: str,
    paragraphs: Sequence[str],
    link: Optional[str] = None,
    link_label: Optional[str] = None,
    footer: Optional[str] = None,
) -> EmailContent:
    """Build both bodies from the same content. `paragraphs` are plain text (a "\\n"
    inside one becomes a line break). The link, when given, comes after the paragraphs:
    as a labelled line in the text part, and as a button plus the raw address in HTML,
    since some mail apps strip buttons."""
    text_parts = list(paragraphs)
    if link:
        text_parts.append(f"{link_label}:\n{link}" if link_label else link)
    if footer:
        text_parts.append(footer)
    text = "\n\n".join(text_parts)

    html_parts = [
        f'<p style="margin:0 0 16px;line-height:1.5;">{_escape_lines(p)}</p>' for p in paragraphs
    ]
    if link:
        safe_link = escape(link, quote=True)
        label = escape(link_label or "Open in Healthcare Manager")
        html_parts.append(
            '<p style="margin:24px 0;">'
            f'<a href="{safe_link}" style="background:#2563eb;color:#ffffff;padding:10px 18px;'
            f'border-radius:6px;text-decoration:none;display:inline-block;">{label}</a></p>'
            '<p style="margin:0 0 16px;font-size:13px;color:#6b7280;">'
            f'Or copy this address into your browser:<br>{safe_link}</p>'
        )
    if footer:
        html_parts.append(
            f'<p style="margin:24px 0 0;font-size:13px;color:#6b7280;">{_escape_lines(footer)}</p>'
        )
    html = (
        '<!DOCTYPE html><html><body style="margin:0;padding:0;background:#f3f4f6;">'
        '<div style="max-width:560px;margin:0 auto;padding:24px;">'
        f'<div style="background:#ffffff;border-radius:8px;padding:24px;{_FONT}">'
        f'<h1 style="margin:0 0 16px;font-size:20px;">{escape(subject)}</h1>'
        + "".join(html_parts)
        + "</div>"
        f'<p style="margin:16px 0 0;font-size:12px;color:#9ca3af;text-align:center;{_FONT}">'
        "Healthcare Manager</p>"
        "</div></body></html>"
    )
    return EmailContent(subject=subject, text=text, html=html)


def _escape_lines(value: str) -> str:
    return "<br>".join(escape(line) for line in value.split("\n"))
