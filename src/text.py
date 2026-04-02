import marko
import marko.inline
import requests
import json
import os
import re
import html
from typing import Optional
from pygments import highlight
from pygments.formatters.html import HtmlFormatter
from pygments.lexers import get_lexer_by_name
from pygments.util import ClassNotFound

from .config import TWEMOJI_LIST_URL, TWEMOJI_LIST_PATH, FALLBACK_REACTION, jinja_env, logger
from .cache import cache_resource

TWEMOJI_CDN = "https://cdn.jsdelivr.net/gh/twitter/twemoji@14.0.2/assets/svg/{hexcode}.svg"
TWEMOJI_LIST = None
TWEMOJI_MAP = None
CODEHILITE_FORMATTER = HtmlFormatter(style="one-dark", cssclass="codehilite")
PROTECTED_HTML_PATTERNS = (
    re.compile(r"<a\b.*?</a>", re.DOTALL),
    re.compile(r"<pre\b.*?</pre>", re.DOTALL),
    re.compile(r"<code\b.*?</code>", re.DOTALL),
)
URL_PATTERN = re.compile(r"(?P<url>https?://[^\s<]+[^\s<.,:;\"')\]])")

def gen_twemoji_list():

    res = requests.get(TWEMOJI_LIST_URL)
    assert res.ok

    twemojis = []

    for element in res.json():

        skins = [element]
        if "skins" in element:
            skins.extend(element["skins"])
        
        for skin in skins:
            twemoji = {
                "emoji": skin["emoji"],
                "hexcode": skin["hexcode"]
            }
            twemojis.append(twemoji)
    
    twemojis.sort(key=lambda tw: len(tw["emoji"]), reverse=True)
    
    with open(TWEMOJI_LIST_PATH, "w") as f:
        json.dump(twemojis, f)

    return twemojis

def get_twemoji_list():
    global TWEMOJI_LIST

    if TWEMOJI_LIST is not None:
        return TWEMOJI_LIST
    
    if not os.path.exists(TWEMOJI_LIST_PATH):
        TWEMOJI_LIST = gen_twemoji_list()
        return TWEMOJI_LIST

    with open(TWEMOJI_LIST_PATH, "r") as f:
        TWEMOJI_LIST = json.load(f)
        return TWEMOJI_LIST

def get_twemoji_map() -> dict[str, str]:
    global TWEMOJI_MAP

    if TWEMOJI_MAP is not None:
        return TWEMOJI_MAP

    res = {}
    for twj in get_twemoji_list():
        res[twj["emoji"]] = twj["hexcode"]
    
    TWEMOJI_MAP = res
    return TWEMOJI_MAP

# Stolen from https://github.com/ShahriarKh/twemoji-cheatsheet/blob/main/utils/getEmojiUrl.js
def twemoji_url(twemoji: Optional[str] = None, hexcode: Optional[str] = None) -> str:

    if not hexcode:
        assert twemoji is not None, "You need to provide either a hexcode or a twemoji"
        hexcode = get_twemoji_map().get(twemoji)
        if hexcode is None:
            hexcode = "-".join(f"{ord(char):x}" for char in twemoji)

    hexcode = hexcode.lower()

    if hexcode.startswith("00"):
        hexcode = hexcode[2:].replace("-fe0f", "")

    if "1f441" in hexcode:
        hexcode = hexcode.replace("-fe0f", "")

    url = TWEMOJI_CDN.format(hexcode=hexcode)

    return cache_resource(
        path=f"emojis/default/{hexcode}.svg",
        sources=[
            url,
            FALLBACK_REACTION
        ]
    )

def parse_twemojis(text: str) -> str:

    twemoji_template = jinja_env.get_template("twemoji.html")
    substitutions: dict[str, str] = {}

    for twemoji_definition in get_twemoji_list():

        alt: str = twemoji_definition["emoji"]
        hexcode: str = twemoji_definition["hexcode"]

        if alt not in text:
            continue

        substitutions[alt] = twemoji_template.render(
            alt=alt,
            url=twemoji_url(hexcode=hexcode)
        )

    if not substitutions:
        return text

    escaped_subs = {
        re.escape(key): substitutions[key]
        for key in substitutions
    }

    result = re.sub(
        pattern="|".join(escaped_subs),
        repl=lambda m: escaped_subs[re.escape(m.group(0))],
        string=text
    )

    return result

def only_twemoji(text: str) -> str:

    twemoji_map = get_twemoji_map()
    for twemoji in twemoji_map:
        text = text.replace(twemoji, "")
    
    res = all(c in [" "] for c in text) #TODO: Prob define a WHITESPACE variable in conf
    return res

class MarkoStriketrough(marko.inline.InlineElement):

    pattern = r"~~(.+?)~~"
    parse_children = True

class SafeMarkdownRenderer(marko.HTMLRenderer):

    def render_inline_html(self, element) -> str:
        return html.escape(element.children)

    def render_html_block(self, element) -> str:
        return html.escape(element.body)

    def render_fenced_code(self, element) -> str:
        code = element.children[0].children

        try:
            if element.lang:
                lexer = get_lexer_by_name(element.lang, stripall=False)
            else:
                lexer = guess_code_lexer(code)
                if lexer is None:
                    return super().render_fenced_code(element)
        except ClassNotFound:
            return super().render_fenced_code(element)

        return highlight(code, lexer, CODEHILITE_FORMATTER)

MARKDOWN_RENDERER = marko.Markdown(renderer=SafeMarkdownRenderer)

def parse_markdown(text: str) -> str:
    return MARKDOWN_RENDERER.convert(text)

def _protect_html_segments(text: str) -> tuple[str, dict[str, str]]:

    protected: dict[str, str] = {}
    counter = 0

    def replace_match(match: re.Match[str]) -> str:
        nonlocal counter
        token = f"__grimora_protected_{counter}__"
        protected[token] = match.group(0)
        counter += 1
        return token

    result = text
    for pattern in PROTECTED_HTML_PATTERNS:
        result = pattern.sub(replace_match, result)

    return result, protected

def _restore_html_segments(text: str, protected: dict[str, str]) -> str:

    restored = text
    for token, content in protected.items():
        restored = restored.replace(token, content)

    return restored

def codehilite_css() -> str:

    raw_css = CODEHILITE_FORMATTER.get_style_defs(".codehilite")
    scoped_lines = []

    for line in raw_css.splitlines():
        if "{" not in line:
            scoped_lines.append(line)
            continue

        selectors, body = line.split("{", 1)
        scoped_selectors = []

        for selector in selectors.split(","):
            selector = selector.strip()
            if selector.startswith(".codehilite"):
                scoped_selectors.append(selector)
            else:
                scoped_selectors.append(f".codehilite {selector}")

        scoped_lines.append(f"{', '.join(scoped_selectors)} {{{body}")

    return "\n".join(scoped_lines)

def guess_code_lexer(code: str):

    stripped = code.strip()
    if not stripped:
        return None

    lowered = stripped.casefold()

    if ("{{" in stripped or "{%" in stripped or re.search(r"</?[a-z][\w:-]*", stripped, re.IGNORECASE)):
        for alias in ("html+jinja", "html+django", "django", "html"):
            try:
                return get_lexer_by_name(alias, stripall=False)
            except ClassNotFound:
                continue

    if re.search(r"(^|\n)\s*[@.#][^{\n]+\{", stripped) or re.search(r"(^|\n)\s*[a-z-]+\s*:\s*[^;\n]+;?", lowered):
        return get_lexer_by_name("css", stripall=False)

    if (
        re.search(r"(^|\n)\s*(const|let|var|function)\b", stripped)
        or "document." in stripped
        or "window." in stripped
        or "=>" in stripped
    ):
        return get_lexer_by_name("javascript", stripall=False)

    if stripped.startswith("$") or re.search(r"(^|\n)\s*(cd|ls|cat|curl|wget|echo|export|grep|find)\b", lowered):
        return get_lexer_by_name("bash", stripall=False)

    if (stripped.startswith("{") or stripped.startswith("[")) and re.search(r'"\s*:\s*', stripped):
        return get_lexer_by_name("json", stripall=False)

    if re.search(r"\b(select|insert|update|delete|from|where|join)\b", lowered):
        return get_lexer_by_name("sql", stripall=False)

    if re.search(r"(^|\n)\s*(def|class|from|import)\b", stripped) or re.search(r"\bprint\s*\(", stripped):
        return get_lexer_by_name("python", stripall=False)

    return None

def linkify_urls(text: str) -> str:

    return URL_PATTERN.sub(
        lambda match: (
            f'<a class="external-link" href="{match.group("url")}" '
            f'target="_blank" rel="noreferrer noopener">{match.group("url")}</a>'
        ),
        text,
    )

def format_text(text: str, md: bool = False, mentions_map: dict[str, str] = {}, twemojis: bool = False) -> str:

    if md:
        res = parse_markdown(text).strip()
        res, protected = _protect_html_segments(res)
    else:
        res = html.escape(text)
        protected = {}

    mention_template = jinja_env.get_template("mention.html")

    res = linkify_urls(res)

    if twemojis:
        res = parse_twemojis(res)

    for uid in mentions_map:
        res = res.replace(f"&lt;@{uid}&gt;", mention_template.render(username=mentions_map[uid]))

    if protected:
        res = _restore_html_segments(res, protected)

    return res

def format_inline_preview(text: str, mentions_map: dict[str, str] = {}, twemojis: bool = False) -> str:

    collapsed = " ".join(text.splitlines())
    res = html.escape(collapsed)

    mention_template = jinja_env.get_template("mention.html")

    if twemojis:
        res = parse_twemojis(res)

    for uid in mentions_map:
        res = res.replace(f"&lt;@{uid}&gt;", mention_template.render(username=mentions_map[uid]))

    return res

def format_bytesize(size: int):

    symbols = ["KB", "MB", "GB", "TB", "PB", "EB", "ZB", "YB"]
    
    if size >= 1024**len(symbols):
        return "1 fuckton"

    size = max(size, 1024) # This is how discord does it

    idx = 0
    while size // (1024**(idx+2)):
        idx += 1
    
    size //= (1024**(idx))
    size /= 1024

    return f"{size:.2f} {symbols[idx]}"
