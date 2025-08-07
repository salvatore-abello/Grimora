import os
from urllib.parse import urlparse
import requests
import shutil

from .config import CACHE_DIRECTORY, CACHE_URL

def cache_resource(path: str, sources: list[str]):

    destination = os.path.join(CACHE_DIRECTORY, path)
    assert destination.startswith(CACHE_DIRECTORY), "Invalid destination"

    destination_url = destination.replace(CACHE_DIRECTORY, CACHE_URL)
    if os.path.isfile(destination):
        return destination_url

    os.makedirs(os.path.dirname(destination), exist_ok=True)

    for source in sources:

        parsed_url = urlparse(source)

        if parsed_url.scheme in ["http", "https"]:
            
            res = requests.get(source)
            if not res.ok:
                continue    
            
            with open(destination, "wb") as f:
                f.write(res.content)
            break

        elif parsed_url.scheme == "file":
            
            file_path = parsed_url.path
            if not os.path.isfile(file_path):
                continue
            
            shutil.copy(file_path, destination)
            break

    return destination_url


            

    