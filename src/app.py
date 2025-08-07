import os
from typing import Union, List, Annotated
import tempfile
import shutil

from fastapi import FastAPI, UploadFile, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlmodel import select

from .parser import parse_transcript
from . import config
from .config import logger
from .database import create_db_and_tables, SessionDep, TranscriptInfo
from .utils import search_score

app = FastAPI()

app.mount(config.CACHE_URL,       StaticFiles(directory=config.CACHE_DIRECTORY),                    name="cache")
app.mount(config.TRANSCRIPTS_URL, StaticFiles(directory=config.TRANSCRIPTS_DIRECTORY, html = True), name="transcripts")
app.mount("/static",              StaticFiles(directory=config.STATIC_DIRECTORY),                   name="statics")

@app.on_event("startup")
def on_startup():
    create_db_and_tables()

@app.get("/")
def get_root():
    template = config.jinja_env.get_template("index.html")
    return HTMLResponse(template.render())

@app.get("/search")
def get_search(session: SessionDep, query: str = ""):
    
    point_bins = {}

    for info in session.exec(select(TranscriptInfo)).all():
        score = search_score(query, info.name)

        if score not in point_bins:
            point_bins[score] = []
        point_bins[score].append(info)

    results: list[TranscriptInfo] = []

    for pt in sorted(point_bins, reverse=True):
        infos = point_bins[pt]
        infos.sort(key=lambda x: x.message_start, reverse=True)
        results.extend(infos)

    template = config.jinja_env.get_template("search.html")
    return HTMLResponse(
        template.render(
            query=query,
            results=results,
            transcripts_url=config.TRANSCRIPTS_URL
        )
    )

@app.get("/upload")
def get_upload():
    template = config.jinja_env.get_template("upload.html")
    return HTMLResponse(template.render())

@app.post("/upload")
def post_upload(name: Annotated[str, Form()], description: Annotated[str, Form()], files: List[UploadFile], session: SessionDep):

    assert len(files) == 1, "You need to provide a zip file"
    file = files[0]
    assert file.filename.endswith(".zip"), "Wrong file type"

    filename = file.filename[:-len(".zip")]
    assert all(c in config.SAFE_ALPHABET for c in filename), "Invalid characters in zip name"

    with tempfile.TemporaryDirectory() as tmpdir:
    
        archive_path = os.path.join(tmpdir, filename)
        zip_path = os.path.join(archive_path, "og.zip")

        os.makedirs(archive_path)
        
        with open(zip_path, "wb") as dst:
            shutil.copyfileobj(file.file, dst)
            
        shutil.unpack_archive(
            filename=zip_path,
            extract_dir=archive_path,
            format="zip",
            #filter="data" TODO: wtf is going on here
        )
        
        transcript = parse_transcript(archive_path, name=name, description=description)
        
        storage_path = os.path.join(config.ARCHIVES_DIRECTORY, f"{transcript.id}.zip")
        shutil.copy(zip_path, storage_path)

        transcript_path = os.path.join(config.TRANSCRIPTS_DIRECTORY, str(transcript.id))
        os.makedirs(transcript_path)
        for channel in transcript.channels:
            channel_path = os.path.join(transcript_path, f"{channel.id}.html")
            with open(channel_path, "w", encoding="utf8") as f:
                f.write(transcript.render_channel(channel=channel))

        channel_path = os.path.join(transcript_path, f"index.html")
        with open(channel_path, "w", encoding="utf8") as f:
            f.write(transcript.render_index())
        
        info = transcript.info

        session.add(info)
        session.commit()
        session.refresh(info)

    return RedirectResponse(
        url=transcript.url,
        status_code=302
    )
