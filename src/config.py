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

AUTH_USERNAME_ENV       = "GRIMORA_AUTH_USERNAME"
AUTH_PASSWORD_ENV       = "GRIMORA_AUTH_PASSWORD"
AUTH_REALM              = os.getenv("GRIMORA_AUTH_REALM", "Grimora")


def get_auth_username() -> str:
    return os.getenv(AUTH_USERNAME_ENV, "").strip()


def get_auth_password() -> str:
    return os.getenv(AUTH_PASSWORD_ENV, "")


def validate_auth_configuration() -> None:
    if get_auth_username() == "" or get_auth_password() == "":
        raise RuntimeError(
            f"{AUTH_USERNAME_ENV} and {AUTH_PASSWORD_ENV} must be set before starting Grimora."
        )


jinja_env = jinja2.Environment(loader=jinja2.FileSystemLoader(TEMPLATE_DIRECTORY))
logger = logging.getLogger("grimora")
