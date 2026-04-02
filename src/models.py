from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from datetime import datetime, UTC
from uuid import uuid4
from sqlmodel import Field, SQLModel

from .config import jinja_env, TRANSCRIPTS_URL
from .text import format_text, format_inline_preview, format_bytesize, only_twemoji
from .utils import url_join


def attachment_icon(filename: str, content_type: str) -> str:
    lowered_filename = filename.lower()
    lowered_type = content_type.lower()

    if lowered_filename.endswith(".zip") or "zip" in lowered_type:
        return "/static/attachment_icon_zip.svg"

    return "/static/attachment_icon_generic.svg"

class MessageContent:
    pass

class MessageContentText(MessageContent):
    
    raw_text: str
    text: str
    onlytwemoji: bool

    def __init__(self, text: str, mentions_map: dict[str, str]):

        self.raw_text = text
        self.text = format_text(text, md=True, mentions_map=mentions_map, twemojis=True)
        self.onlytwemoji = only_twemoji(text)

@dataclass
class MessageContentImage(MessageContent):
    
    url: str

@dataclass
class MessageContentVideo(MessageContent):

    url: str
    filename: str
    content_type: str

@dataclass
class MessageContentGifEmbed(MessageContent):

    url: str
    original_url: str
    poster_url: Optional[str]
    provider: str
    width: Optional[int]
    height: Optional[int]

class MessageContentAttachment(MessageContent):
    
    url: str
    filename: str
    size: int
    content_type: str
    icon: str

    def __init__(self, url: str, filename: str, size: int, content_type: str):
        
        self.url = url
        self.filename = filename
        self.content_type = content_type
        self.icon = attachment_icon(filename=filename, content_type=content_type)

        self.size = format_bytesize(size)

@dataclass
class MessageReaction:
    
    url: str
    amount: int

class MessageReply:

    author: str
    avatar: str
    raw_text: str
    text: str
    
    mentions_map: dict[str, str]

    def __init__(self, author: str, avatar: str, text: str, mentions_map: dict[str, str]):
        
        self.author = author
        self.avatar = avatar
        self.raw_text = text

        self.text = format_inline_preview(text, mentions_map=mentions_map, twemojis=True)

class Message:
    continuation: bool
    id: str
    author: str
    avatar: str

    timestamp: datetime
    content: list[MessageContent]
    reactions: list[MessageReaction]

    @property
    def anchor(self) -> str:
        return f"message-{self.id}"

    @property
    def searchable_text(self) -> str:
        pieces = [self.author]

        if hasattr(self, "reply") and getattr(self, "reply") is not None:
            reply = getattr(self, "reply")
            pieces.append(reply.author)
            pieces.append(reply.raw_text)

        for element in self.content:
            if isinstance(element, MessageContentText):
                pieces.append(element.raw_text)
            elif isinstance(element, MessageContentAttachment):
                pieces.append(element.filename)
            elif isinstance(element, MessageContentVideo):
                pieces.append(element.filename)

        return " ".join(piece for piece in pieces if piece)

class MessageFull(Message):

    continuation: bool = False

    reply: Optional[MessageReply]
    author: str
    avatar: str
    timestamp: datetime
    content: list[MessageContent]
    reactions: list[MessageReaction]

    def __init__(
            self,
            id: str,
            reply: Optional[MessageReply],
            author: str,
            avatar: str,
            timestamp: datetime,
            content: list[MessageContent],
            reactions: list[MessageReaction]
        ):
        self.id = id
        self.reply = reply
        self.author = author
        self.avatar = avatar
        self.timestamp = timestamp
        self.content = content
        self.reactions = reactions

class MessageContinuation(Message):

    continuation: bool = True

    timestamp: datetime
    content: list[MessageContent]
    reactions: list[MessageReaction]

    def __init__(
            self,
            id: str,
            author: str,
            avatar: str,
            timestamp: datetime,
            content: list[MessageContent],
            reactions: list[MessageReaction]
        ):
        self.id = id
        self.author = author
        self.avatar = avatar
        self.timestamp = timestamp
        self.content = content
        self.reactions = reactions

class Channel:

    parent: Optional[Transcript]

    id: str
    name: str
    messages: list[Message]

    def __init__(self, name: str, messages: list[Message], id: Optional[str] = None, parent: Optional[Transcript] = None):

        self.name = name
        self.messages = messages
        
        self.id = id if id else str(uuid4())
        self.parent = parent

    @property
    def url(self) -> Optional[str]:
        if not self.parent:
            return None
        return url_join(self.parent.url, "channels", self.id)

class TranscriptInfo(SQLModel, table=True):
    __tablename__ = "transcripts"
    id: str                 = Field(primary_key=True)
    name: str               = Field()
    description: str        = Field()
    added: datetime         = Field(index=True)
    channel_count: int      = Field(default=0)
    message_count: int      = Field(default=0)
    part_count: int         = Field(default=1)
    message_start: datetime = Field(index=True)
    message_end: datetime   = Field(index=True)

class Transcript:

    added: datetime
    id: str
    name: str
    description: str

    channels: list[Channel]

    def __init__(self, name: str, description: str, channels: list[Channel], id: Optional[str] = None, added: Optional[datetime] = None):
        
        self.name = name
        self.description = description
        self.channels = channels

        self.id = id if id else str(uuid4())
        self.added = added if added else datetime.now(UTC)

        for channel in self.channels:
            channel.parent = self
            
    @property
    def message_start(self, default=datetime(2006, 6, 30, tzinfo=UTC)) -> datetime:

        big_date = datetime(9999, 1, 1, tzinfo=UTC)
        result = big_date
        for channel in self.channels:
            for message in channel.messages:
                result = min(result, message.timestamp)
        
        if result == big_date:
            result = default
        
        return result

    @property
    def message_end(self, default=datetime(2006, 6, 30, tzinfo=UTC)) -> datetime:

        small_date = datetime(1, 1, 1, tzinfo=UTC)
        result = small_date
        for channel in self.channels:
            for message in channel.messages:
                result = max(result, message.timestamp)
        
        if result == small_date:
            result = default
        
        return result

    @property
    def info(self) -> TranscriptInfo:
        
        return TranscriptInfo(
            id=str(self.id),
            name=self.name,
            description=self.description,
            added=self.added,
            channel_count=len(self.channels),
            message_count=sum(len(channel.messages) for channel in self.channels),
            part_count=1,
            message_start=self.message_start,
            message_end=self.message_end
        )
    
    @property
    def url(self) -> str:
        return url_join(TRANSCRIPTS_URL, self.id)

    def render_index(self) -> str:
        template = jinja_env.get_template("transcript.html")
        return template.render(
            view_mode="info",
            transcript=self,
            current_channel=None,
            selected_channel_id=None,
            transcript_query="",
        )

    def render_channel(self, channel: Channel) -> str:
        template = jinja_env.get_template("transcript.html")
        return template.render(
            view_mode="channel",
            transcript=self,
            current_channel=channel,
            messages=channel.messages,
            selected_channel_id=channel.id,
            transcript_query="",
        )
    
