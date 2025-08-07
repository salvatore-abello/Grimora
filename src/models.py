from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from datetime import datetime, UTC
from uuid import UUID, uuid4
from sqlmodel import Field, SQLModel

from .config import jinja_env, TRANSCRIPTS_URL
from .text import format_text, format_bytesize, only_twemoji
from .utils import url_join

class MessageContent:
    pass

class MessageContentText(MessageContent):
    
    text: str
    onlytwemoji: bool

    def __init__(self, text: str, mentions_map: dict[str, str]):

        self.text = format_text(text, md=True, mentions_map=mentions_map, twemojis=True)
        self.onlytwemoji = only_twemoji(text)

@dataclass
class MessageContentImage(MessageContent):
    
    url: str

@dataclass
class MessageContentVideo(MessageContent):

    url: str
    content_type: str

class MessageContentAttachment(MessageContent):
    
    url: str
    filename: str
    size: int
    content_type: str

    def __init__(self, url: str, filename: str, size: int, content_type: str):
        
        self.url = url
        self.filename = filename
        self.content_type = content_type

        self.size = format_bytesize(size)

@dataclass
class MessageReaction:
    
    url: str
    amount: int

class MessageReply:

    author: str
    avatar: str
    text: str
    
    mentions_map: dict[str, str]

    def __init__(self, author: str, avatar: str, text: str, mentions_map: dict[str, str]):
        
        self.author = author
        self.avatar = avatar

        self.text = format_text(text, md=True, mentions_map=mentions_map, twemojis=True)

class Message:
    continuation: bool

    timestamp: datetime
    content: list[MessageContent]
    reactions: list[MessageReaction]

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
            reply: Optional[MessageReply],
            author: str,
            avatar: str,
            timestamp: datetime,
            content: list[MessageContent],
            reactions: list[MessageReaction]
        ):
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
            timestamp: datetime,
            content: list[MessageContent],
            reactions: list[MessageReaction]
        ):
        self.timestamp = timestamp
        self.content = content
        self.reactions = reactions

class Channel:

    parent: Optional[Transcript]

    id: UUID
    name: str
    messages: list[Message]

    def __init__(self, name: str, messages: list[Message], id: Optional[UUID] = None, parent: Optional[Transcript] = None):

        self.name = name
        self.messages = messages
        
        self.id = id if id else uuid4()
        self.parent = parent

    @property
    def url(self) -> Optional[str]:
        if not self.parent:
            return None
        return url_join(self.parent.url, f"{self.id}.html")

class TranscriptInfo(SQLModel, table=True):
    __tablename__ = "transcripts"
    id: str                 = Field(primary_key=True)
    name: str               = Field()
    description: str        = Field()
    added: datetime         = Field(index=True)
    message_start: datetime = Field(index=True)
    message_end: datetime   = Field()

class Transcript:

    added: datetime
    id: UUID
    name: str
    description: str

    channels: list[Channel]

    def __init__(self, name: str, description: str, channels: list[Channel], id: Optional[UUID] = None, added: Optional[datetime] = None):
        
        self.name = name
        self.description = description
        self.channels = channels

        self.id = id if id else uuid4()
        self.added = added if added else datetime.now()

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
            message_start=self.message_start,
            message_end=self.message_end
        )
    
    @property
    def url(self) -> str:
        return url_join(TRANSCRIPTS_URL, self.id)

    def render_index(self) -> str:
        template = jinja_env.get_template("transcript.html")
        return template.render(
            info=True,
            transcript=self
        )

    def render_channel(self, channel: Channel) -> str:
        template = jinja_env.get_template("transcript.html")
        return template.render(
            info=False,
            transcript=self,
            messages=channel.messages
        )
    
