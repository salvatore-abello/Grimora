from typing import Any
from .config import SEARCH_ALPHABET

def url_join(base: str, *paths: Any):

    for path in paths:
        base = f"{base.rstrip('/')}/{str(path).lstrip('/')}"
    
    return base

def search_score(query: str, text: str) -> int:    

    def format_search(val: str) -> str:
        return ''.join([x if x in SEARCH_ALPHABET else "" for x in val.lower()])
    
    text = format_search(text)
    subqueries = [format_search(x) for x in query.split(" ")]

    score = sum(
        1 if subquery in text else 0
        for subquery in subqueries
    )

    return score