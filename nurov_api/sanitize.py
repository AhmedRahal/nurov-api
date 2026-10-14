import html
import logging
import re

log = logging.getLogger(__name__)

ALLOWED_TAGS = {
    "p", "br", "span", "b", "strong", "i", "em", "u", "s", "strike",
    "h1", "h2", "h3", "blockquote", "pre", "code", "ul", "ol", "li",
    "a", "img", "sub", "sup",
}
ALLOWED_ATTRS = {
    "a": {"href", "target"},
    "img": {"src", "alt"},
    "*": {"class", "data-list", "data-checked", "style"},
}
ALLOWED_URL_SCHEMES = {"http", "https", "mailto", "data"}

try:
    import nh3
except ImportError:
    nh3 = None
    log.warning("nh3 not installed: falling back to plain-text-only sanitizing. pip install nh3")


_DATA_IMG_RE = re.compile(r"^data:image/(png|jpeg|gif|webp);base64,[a-z0-9+/=\s]+$", re.I)
_QUILL_CLASS_RE = re.compile(r"^ql-[a-z0-9-]+$")
_SAFE_STYLE_PROPS = {"color", "background-color", "text-align"}
_SAFE_STYLE_VALUE = re.compile(r"^[#a-z0-9(),.%\s-]+$", re.I)


def _safe_style(value):
    kept = []
    for decl in value.split(";"):
        prop, _, val = decl.partition(":")
        prop, val = prop.strip().lower(), val.strip()
        if prop in _SAFE_STYLE_PROPS and val and _SAFE_STYLE_VALUE.match(val) and "url(" not in val.lower():
            kept.append(f"{prop}: {val}")
    return "; ".join(kept) or None


def _attr_filter(tag, attr, value):
    if attr == "class":
        tokens = [t for t in value.split() if _QUILL_CLASS_RE.match(t)]
        return " ".join(tokens) or None
    if attr == "style":
        return _safe_style(value)
    if attr in ("href", "src"):
        v = value.strip()
        if v.lower().startswith("data:"):
            return v if tag == "img" and attr == "src" and _DATA_IMG_RE.match(v) else None
    return value


def sanitize_html(dirty):
    if not dirty:
        return ""
    if nh3 is None:
        return html.escape(re.sub(r"<[^>]*>", "", dirty))
    return nh3.clean(
        dirty,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRS,
        url_schemes=ALLOWED_URL_SCHEMES,
        link_rel="noopener noreferrer",
        attribute_filter=_attr_filter,
    )


def strip_to_text(value):
    if nh3 is not None:
        return html.unescape(nh3.clean(value or "", tags=set())).strip()
    return html.unescape(re.sub(r"<[^>]*>", "", value or "")).strip()
