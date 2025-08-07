import os
from typing import Optional
from datetime import datetime, timedelta
import json

from .config import FALLBACK_AVATAR, FALLBACK_REACTION
from .cache import cache_resource
from .models import *
from .text import twemoji_url

def parse_name(raw_element) -> str:
    return raw_element["global_name"] if raw_element["global_name"] else raw_element["username"]

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

def parse_content(raw_element, path: str) -> list[MessageContent]:

    content = []

    if raw_element["content"]:
        content.append(MessageContentText(
            text=raw_element["content"],
            mentions_map=parse_mentions_map(raw_element)))

    channel_id = raw_element["channel_id"]

    for raw_attachment in raw_element["attachments"]:
        
        #print(raw_attachment)

        attachment_id = raw_attachment["id"]
        attachment_filename = raw_attachment["filename"]

        url = cache_resource(
            path=f"attachments/{channel_id}/{attachment_id}/{attachment_filename}",
            sources=[
                "file:" + os.path.join(path, f"{attachment_id}.{attachment_filename}")
            ]
        )

        if raw_attachment["content_type"].startswith("image/"):
            content.append(MessageContentImage(url=url))
        else:
            content.append(MessageContentAttachment(
                url=url,
                filename=raw_attachment["filename"],
                size=raw_attachment["size"],
                content_type=raw_attachment["content_type"]
                ))
            
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
        timestamp=parse_timestamp(raw_element),
        content=parse_content(raw_element, path),
        reactions=parse_reactions(raw_element),
    )

    return message

def parse_channel(path: str) -> Channel:

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
            (last_fullmessage_timestamp - timestamp) < timedelta(minutes=5) and \
            raw_element["message_reference"] is None:
            messages.append(parse_continuemessage(raw_element, path_dir))
            continue

        messages.append(parse_fullmessage(raw_element, path_dir))
        last_fullmessage_timestamp = timestamp
        last_fullmessage_author = raw_element["author"]["id"]

    channel = Channel(
        name=channel_name,
        messages=messages
    )

    return channel

def parse_transcript(path: str, name: Optional[str] = None, description: str = "") -> Transcript:

    assert os.path.isdir(path), "The path provided is not a directory"

    transcript_name = os.path.basename(path)
    channels = []

    for directory in os.listdir(path):

        directory_path = os.path.join(path, directory)
        if not os.path.isdir(directory_path):
            print(f"[WARN] File {directory_path} shouldn't be here :/ ")
            continue

        channel_path = os.path.join(directory_path, directory + '.json')
        if not os.path.isfile(channel_path):
            print(f"[WARN] Directory {directory_path} doesnt have a json file")
            continue
        
        channels.append(parse_channel(channel_path))
    
    return Transcript(
        name=name if (name is not None) else transcript_name,
        description=description,
        channels=channels)