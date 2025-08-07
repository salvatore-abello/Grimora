import marko
import marko.inline
import requests
import json
import os
import re
import html
from typing import Optional

from .config import TWEMOJI_LIST_URL, TWEMOJI_LIST_PATH, FALLBACK_REACTION, jinja_env, logger
from .cache import cache_resource

TWEMOJI_CDN = "https://cdn.jsdelivr.net/gh/twitter/twemoji@14.0.2/assets/svg/{hexcode}.svg"
TWEMOJI_LIST = None
TWEMOJI_MAP = None

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
        hexcode = get_twemoji_map()[twemoji]

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

def parse_markdown(text: str) -> str:
    return marko.convert(text)

def format_text(text: str, md: bool = False, mentions_map: dict[str, str] = {}, twemojis: bool = False) -> str:

    res = html.escape(text)

    if md:
        res = parse_markdown(res)

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
