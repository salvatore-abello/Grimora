from pathlib import Path
from typing import Annotated
import shutil

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import config
from .archive_store import archive_store
from .text import codehilite_css
from .utils import highlight_matches, make_excerpt, search_score

app = FastAPI()

MAX_TRANSCRIPT_SEARCH_RESULTS = 80

app.mount(config.CACHE_URL,       StaticFiles(directory=config.CACHE_DIRECTORY),                    name="cache")
app.mount("/static",              StaticFiles(directory=config.STATIC_DIRECTORY),                   name="statics")
config.jinja_env.globals["codehilite_css"] = codehilite_css()

@app.on_event("startup")
def on_startup():
    archive_store.refresh()


def sort_infos(query: str):
    infos = archive_store.list_infos()
    normalized_query = query.strip()

    if normalized_query == "":
        return sorted(
            infos,
            key=lambda info: (info.message_end, info.message_start, info.added),
            reverse=True,
        )

    point_bins = {}

    for info in infos:
        score = search_score(normalized_query, f"{info.name} {info.description}")
        if score == 0:
            continue

        if score not in point_bins:
            point_bins[score] = []
        point_bins[score].append(info)

    results = []

    for points in sorted(point_bins, reverse=True):
        bucket = point_bins[points]
        bucket.sort(key=lambda info: (info.message_start, info.added), reverse=True)
        results.extend(bucket)

    return results


def summarize_infos(infos):
    return {
        "archive_count": len(infos),
        "message_count": sum(info.message_count for info in infos),
        "channel_count": sum(info.channel_count for info in infos),
    }


def build_transcript_search_results(transcript, query: str):
    normalized_query = query.strip()
    if normalized_query == "":
        return []

    results = []

    for channel in transcript.channels:
        for message in channel.messages:
            searchable_text = f"{channel.name} {message.searchable_text}"
            score = search_score(normalized_query, searchable_text)
            if score == 0:
                continue

            results.append(
                {
                    "score": score,
                    "channel_id": channel.id,
                    "channel_name": channel.name,
                    "channel_html": highlight_matches(channel.name, normalized_query),
                    "message_id": message.id,
                    "message_anchor": message.anchor,
                    "author": message.author,
                    "author_html": highlight_matches(message.author, normalized_query),
                    "avatar": message.avatar,
                    "timestamp": message.timestamp,
                    "excerpt_html": make_excerpt(search_preview_text(message), normalized_query),
                    "url": f"{channel.url}#{message.anchor}",
                }
            )

    results.sort(key=lambda hit: (hit["score"], hit["timestamp"]), reverse=True)
    return results[:MAX_TRANSCRIPT_SEARCH_RESULTS]


def search_preview_text(message):
    for content in message.content:
        if hasattr(content, "raw_text") and getattr(content, "raw_text"):
            return content.raw_text
        if hasattr(content, "filename") and getattr(content, "filename"):
            return getattr(content, "filename")

    if hasattr(message, "reply") and getattr(message, "reply") is not None:
        reply = getattr(message, "reply")
        if reply.raw_text:
            return reply.raw_text

    return f"Message by {message.author}"

@app.get("/")
def get_root():
    results = sort_infos("")
    template = config.jinja_env.get_template("index.html")
    return HTMLResponse(
        template.render(
            results=results,
            stats=summarize_infos(results),
            all_transcripts=results,
            transcripts_url=config.TRANSCRIPTS_URL
        )
    )

@app.get("/search")
def get_search(query: str = ""):
    all_transcripts = sort_infos("")
    results = sort_infos(query)
    template = config.jinja_env.get_template("search.html")
    return HTMLResponse(
        template.render(
            query=query,
            results=results,
            stats=summarize_infos(results),
            all_transcripts=all_transcripts,
            transcripts_url=config.TRANSCRIPTS_URL
        )
    )

@app.get("/upload")
def get_upload():
    template = config.jinja_env.get_template("upload.html")
    all_transcripts = sort_infos("")
    return HTMLResponse(
        template.render(
            all_transcripts=all_transcripts,
            transcripts_url=config.TRANSCRIPTS_URL,
        )
    )

@app.post("/upload")
def post_upload(
    files: Annotated[list[UploadFile], File()],
    name: Annotated[str, Form()] = "",
    description: Annotated[str, Form()] = "",
):
    if len(files) == 0:
        raise HTTPException(status_code=400, detail="Provide one zip file or one split zip archive.")

    grouped_files: dict[str, list[tuple[str, UploadFile]]] = {}

    for file in files:
        raw_filename = (file.filename or "").strip()
        filename = Path(raw_filename).name.strip()

        if filename in {"", ".", ".."}:
            raise HTTPException(status_code=400, detail="One of the uploaded files has an invalid filename.")

        archive_key = archive_store.archive_key_from_filename(filename)
        if archive_key is None:
            raise HTTPException(status_code=400, detail="Uploads must be .zip files or .zip.partN files.")

        grouped_files.setdefault(archive_key, []).append((filename, file))

    if len(grouped_files) != 1:
        raise HTTPException(
            status_code=400,
            detail="Upload exactly one archive at a time. Split archives can include multiple .part files.",
        )

    archive_key, uploaded_parts = next(iter(grouped_files.items()))
    destination_directory = Path(config.TRANSCRIPTS_DIRECTORY)
    destination_directory.mkdir(parents=True, exist_ok=True)

    for filename, file in uploaded_parts:
        destination_path = destination_directory / filename
        with open(destination_path, "wb") as destination_file:
            shutil.copyfileobj(file.file, destination_file)

    archive_store.save_metadata(archive_key, name=name, description=description)
    archive_store.refresh()

    return RedirectResponse(
        url=f"{config.TRANSCRIPTS_URL}{archive_store.transcript_id_from_archive_key(archive_key)}",
        status_code=303
    )


@app.get("/favicon.ico", include_in_schema=False)
def get_favicon():
    return FileResponse(
        Path(config.STATIC_DIRECTORY) / "logo.png",
        media_type="image/png",
    )


@app.get("/transcripts/{transcript_id}")
def get_transcript(transcript_id: str):
    try:
        transcript = archive_store.get_transcript(transcript_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Transcript not found.") from exc

    template = config.jinja_env.get_template("transcript.html")
    return HTMLResponse(
        template.render(
            view_mode="info",
            transcript=transcript,
            all_transcripts=sort_infos(""),
            current_channel=None,
            selected_channel_id=None,
            transcript_query="",
        )
    )


@app.get("/transcripts/{transcript_id}/channels/{channel_id}")
def get_channel(transcript_id: str, channel_id: str):
    try:
        transcript = archive_store.get_transcript(transcript_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Transcript not found.") from exc

    channel = next((channel for channel in transcript.channels if channel.id == channel_id), None)
    if channel is None:
        raise HTTPException(status_code=404, detail="Channel not found.")

    template = config.jinja_env.get_template("transcript.html")
    return HTMLResponse(
        template.render(
            view_mode="channel",
            transcript=transcript,
            all_transcripts=sort_infos(""),
            current_channel=channel,
            messages=channel.messages,
            selected_channel_id=channel.id,
            transcript_query="",
        )
    )


@app.get("/transcripts/{transcript_id}/search")
def get_transcript_search(transcript_id: str, query: str = ""):
    try:
        transcript = archive_store.get_transcript(transcript_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Transcript not found.") from exc

    template = config.jinja_env.get_template("transcript.html")
    return HTMLResponse(
        template.render(
            view_mode="search",
            transcript=transcript,
            all_transcripts=sort_infos(""),
            current_channel=None,
            selected_channel_id=None,
            transcript_query=query,
            search_results=build_transcript_search_results(transcript, query),
        )
    )
