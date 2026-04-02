import os
from typing import Optional
from datetime import datetime, timedelta
import json
from urllib.parse import urlparse

from .config import FALLBACK_AVATAR, FALLBACK_REACTION
from .cache import cache_resource
from .models import *
from .text import twemoji_url
from .utils import stable_slug

def parse_name(raw_element) -> str:
    return raw_element.get("global_name") or raw_element["username"]

def parse_mentions_map(raw_element) -> dict[str, str]:
    mentions_map = { raw_mention["id"]: '@' + parse_name(raw_mention) for raw_mention in raw_element["mentions"] }
    return mentions_map

def parse_avatar(raw_element) -> str:

    user_id = raw_element["author"]["id"]
    avatar_id = raw_element["author"]["avatar"]

    sources = []
    
    if avatar_id:
        avatar_url = f"https://cdn.discordapp.com/avatars/{user_id}/{avatar_id}.webp"
        sources.append(avatar_url)
    else:
        avatar_id = "default"

    sources.append(FALLBACK_AVATAR)
    return cache_resource(
            path=f"avatars/{user_id}/{avatar_id}.webp",
            sources=sources
        )

def _cached_embed_url(channel_id: str, message_id: str, embed_index: int, variant: str, source_url: str) -> str:

    parsed_url = urlparse(source_url)
    filename = os.path.basename(parsed_url.path) or f"{variant}-{embed_index}"
    return cache_resource(
        path=f"embeds/{channel_id}/{message_id}/{embed_index}-{variant}-{filename}",
        sources=[source_url],
    )

def parse_embeds(raw_element) -> list[MessageContent]:

    content = []
    channel_id = raw_element["channel_id"]
    message_id = parse_message_id(raw_element)

    for embed_index, raw_embed in enumerate(raw_element.get("embeds") or []):
        embed_type = raw_embed.get("type")

        if embed_type != "gifv":
            continue

        video_url = raw_embed.get("video", {}).get("url")
        if not video_url:
            continue

        poster_source = raw_embed.get("thumbnail", {}).get("proxy_url") or raw_embed.get("thumbnail", {}).get("url")
        poster_url = None
        if poster_source:
            poster_url = _cached_embed_url(channel_id, message_id, embed_index, "poster", poster_source)

        content.append(MessageContentGifEmbed(
            url=_cached_embed_url(channel_id, message_id, embed_index, "video", video_url),
            original_url=raw_embed.get("url") or video_url,
            poster_url=poster_url,
            provider=(raw_embed.get("provider", {}) or {}).get("name", ""),
            width=raw_embed.get("video", {}).get("width"),
            height=raw_embed.get("video", {}).get("height"),
        ))

    return content

def parse_content(raw_element, path: str) -> list[MessageContent]:

    content = []
    raw_content = raw_element["content"]
    embeds = parse_embeds(raw_element)
    embed_urls = {
        raw_embed.get("url", "").strip()
        for raw_embed in raw_element.get("embeds") or []
        if raw_embed.get("type") == "gifv" and raw_embed.get("url")
    }

    if raw_content and raw_content.strip() not in embed_urls:
        content.append(MessageContentText(
            text=raw_content,
            mentions_map=parse_mentions_map(raw_element)))

    channel_id = raw_element["channel_id"]

    for raw_attachment in raw_element["attachments"]:
        attachment_id = raw_attachment["id"]
        attachment_filename = raw_attachment["filename"]
        content_type = raw_attachment.get("content_type") or ""

        url = cache_resource(
            path=f"attachments/{channel_id}/{attachment_id}/{attachment_filename}",
            sources=[
                "file:" + os.path.join(path, f"{attachment_id}.{attachment_filename}")
            ]
        )

        if content_type.startswith("image/"):
            content.append(MessageContentImage(url=url))
        elif content_type.startswith("video/"):
            content.append(MessageContentVideo(
                url=url,
                filename=attachment_filename,
                content_type=content_type,
            ))
        else:
            content.append(MessageContentAttachment(
                url=url,
                filename=raw_attachment["filename"],
                size=raw_attachment["size"],
                content_type=content_type
                ))

    content.extend(embeds)
            
    return content

def parse_reactions(raw_element) -> list[MessageReaction]:

    reactions = []

    if raw_element["reactions"] is not None:
        for raw_reaction in raw_element["reactions"]:
            
            raw_twemoji = raw_reaction["emoji"]
            
            if raw_twemoji["id"]:
                url = cache_resource(
                    path=f"emojis/{raw_twemoji["id"]}.png",
                    sources=[
                        f"https://cdn.discordapp.com/emojis/{raw_twemoji["id"]}.png",
                        FALLBACK_REACTION
                    ]
                )
            else:
                url = twemoji_url(twemoji=raw_twemoji["name"])

            reaction = MessageReaction(url=url, amount=raw_reaction["count"])
            reactions.append(reaction)

    return reactions

def parse_timestamp(raw_element) -> datetime:
    return datetime.fromisoformat(raw_element["timestamp"])

def parse_reply(raw_element) -> Optional[MessageReply]:

    if raw_element["referenced_message"] is None:
        return None
    
    author = parse_name(raw_element["referenced_message"]["author"])
    avatar = parse_avatar(raw_element["referenced_message"])
    text = raw_element["referenced_message"]["content"]
    
    reply = MessageReply(
        author=author,
        avatar=avatar,
        text=text,
        mentions_map=parse_mentions_map(raw_element["referenced_message"])
    )

    return reply

def parse_fullmessage(raw_element, path: str) -> MessageFull:

    author = parse_name(raw_element["author"])
    avatar = parse_avatar(raw_element)

    message = MessageFull(
        id=parse_message_id(raw_element),
        reply=parse_reply(raw_element),
        author=author,
        avatar=avatar,
        timestamp=parse_timestamp(raw_element),
        content=parse_content(raw_element, path),
        reactions=parse_reactions(raw_element)
    )

    return message

def parse_continuemessage(raw_element, path: str) -> MessageContinuation:

    message = MessageContinuation(
        id=parse_message_id(raw_element),
        author=parse_name(raw_element["author"]),
        avatar=parse_avatar(raw_element),
        timestamp=parse_timestamp(raw_element),
        content=parse_content(raw_element, path),
        reactions=parse_reactions(raw_element),
    )

    return message


def parse_message_id(raw_element) -> str:
    raw_message_id = raw_element.get("id")
    if raw_message_id:
        return str(raw_message_id)

    return stable_slug(
        f"{raw_element['author']['id']}:{raw_element['timestamp']}:{raw_element['content']}",
        prefix="message",
    )

def parse_channel(path: str, transcript_id: Optional[str] = None) -> Channel:

    assert os.path.isfile(path), "The path provided is not a file"

    path_dir = os.path.dirname(path)
    file_name = os.path.basename(path)

    file_ext = file_name[file_name.rfind('.'):]
    assert file_ext == '.json', "The path provided is not a json file"
    
    channel_name = file_name[:file_name.rfind('.')]

    with open(path, "r", encoding="utf8") as f:
        raw_data = json.load(f)

    if raw_data is None: # Channel is empty
        raw_data = []

    raw_data.sort(key=lambda x: parse_timestamp(x))
    messages = []

    last_fullmessage_author = None
    last_fullmessage_timestamp = datetime.fromtimestamp(0)

    for raw_element in raw_data:

        timestamp = parse_timestamp(raw_element)
        if last_fullmessage_author == raw_element["author"]["id"] and \
            (timestamp - last_fullmessage_timestamp) < timedelta(minutes=5) and \
            raw_element["message_reference"] is None:
            messages.append(parse_continuemessage(raw_element, path_dir))
            continue

        messages.append(parse_fullmessage(raw_element, path_dir))
        last_fullmessage_timestamp = timestamp
        last_fullmessage_author = raw_element["author"]["id"]

    channel = Channel(
        name=channel_name,
        messages=messages,
        id=stable_slug(f"{transcript_id or channel_name}:{channel_name}", prefix="channel"),
    )

    return channel

def parse_transcript(
    path: str,
    name: Optional[str] = None,
    description: str = "",
    transcript_id: Optional[str] = None,
    added: Optional[datetime] = None,
) -> Transcript:

    assert os.path.isdir(path), "The path provided is not a directory"

    transcript_name = os.path.basename(path)
    channels = []

    transcript_identifier = transcript_id or stable_slug(transcript_name, prefix="transcript")

    for directory in sorted(os.listdir(path)):

        directory_path = os.path.join(path, directory)
        if not os.path.isdir(directory_path):
            print(f"[WARN] File {directory_path} shouldn't be here :/ ")
            continue

        channel_path = os.path.join(directory_path, directory + '.json')
        if not os.path.isfile(channel_path):
            print(f"[WARN] Directory {directory_path} doesnt have a json file")
            continue
        
        channels.append(parse_channel(channel_path, transcript_id=transcript_identifier))
    
    return Transcript(
        name=name if (name is not None) else transcript_name,
        description=description,
        channels=channels,
        id=transcript_identifier,
        added=added,
    )
