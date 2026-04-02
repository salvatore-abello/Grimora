import os
import string
import jinja2
import logging

# Please end these in '/'

ARCHIVES_DIRECTORY      = "./archives/"
TEMPLATE_DIRECTORY      = "./templates/"
STATIC_DIRECTORY        = "./static/"

CACHE_DIRECTORY         = "./cache/"
CACHE_URL               = "/cache/"

TRANSCRIPTS_DIRECTORY   = "./transcripts/"
TRANSCRIPTS_URL         = "/transcripts/"
TRANSCRIPTS_METADATA    = os.path.join(TRANSCRIPTS_DIRECTORY, ".grimora-metadata.json")

FALLBACK_AVATAR         = "file:./cache/defaults/default_avatar.webp"
FALLBACK_REACTION       = "file:./cache/defaults/default_reaction.webp"

DATABASE_URL            = "sqlite:///./transcripts.db"

SAFE_ALPHABET           = string.ascii_lowercase + string.ascii_uppercase + string.digits + "-_."
SEARCH_ALPHABET         = string.ascii_lowercase + string.ascii_uppercase + string.digits + " "

TWEMOJI_LIST_URL        = "https://cdn.jsdelivr.net/npm/emojibase-data@16.0.3/en/data.json"
TWEMOJI_LIST_PATH       = "./twemojis.json"

jinja_env = jinja2.Environment(loader=jinja2.FileSystemLoader(TEMPLATE_DIRECTORY))
logger = logging.getLogger("grimora")
