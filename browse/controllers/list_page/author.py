from typing import Optional, Dict, Any, Tuple, List
from urllib.parse import unquote
import re

from flask import request, url_for
from werkzeug.exceptions import BadRequest
from browse.domain.metadata import DocMetadata

from browse.services.listing import ListingItem
from ...services.database import (
    get_user_id_by_author_id, 
    get_user_id_by_orcid,
    get_user_display_name,
    get_orcid_by_user_id,
    get_articles_for_author
)
from browse.services.documents import get_doc_service

from browse.controllers.list_page import (
    dl_for_articles, 
    latexml_links_for_articles,
    authors_for_articles
)



ORCID_URI_PREFIX = 'https://orcid.org'
ORCID_RE = re.compile(r'^(\d{4}\-\d{4}\-\d{4}-\d{3}[\dX])$')

def _get_user_id (raw_id: str) -> Tuple[Optional[int], bool]:
    id = unquote(raw_id) # Check if flask does this automatically
    if ORCID_RE.match(id):
        return get_user_id_by_orcid(id), True
    return get_user_id_by_author_id(id), False

def _get_orcid_uri (user_id: int) -> Optional[str]:
    orcid = get_orcid_by_user_id(user_id)
    if orcid is not None:
        return f'{ORCID_URI_PREFIX}/{orcid}'
    return None

def get_a_page (id: str, ext: str):
    user_id, is_orcid = _get_user_id(id)
    if user_id is None:
        raise BadRequest (f'Author {id} not found')
    
    response_data: Dict[str, Any] = {}

    response_data['display_name'] = get_user_display_name(user_id)
    response_data['auri'] = f'{request.url_root}{id}'
    if is_orcid:
        response_data['orcid'] = f'{ORCID_URI_PREFIX}/{unquote(id)}'
    else:
        response_data['orcid'] = _get_orcid_uri (user_id)
    response_data['title'] = f'{response_data["display_name"]}\'s articles on arXiv'

    listings = get_articles_for_author(user_id)
    for i, item in enumerate(listings):
        setattr(item, 'article', get_doc_service().get_abs(item.id))
        setattr(item, 'list_index', i + 1)

    response_data['abstracts'] = listings
    response_data['downloads'] = dl_for_articles(listings)
    response_data['latexml'] = latexml_links_for_articles(listings)
    response_data['author_links'] = authors_for_articles(listings)

    def author_query(article: DocMetadata, query: str)->str:
        try:
            if article.primary_archive:
                archive = article.primary_archive.id
            else:
                archive = CATEGORIES[article.primary_category.id]['in_archive'] # type: ignore
            return str(url_for('search_archive',
                           searchtype='author',
                           archive=archive,
                           query=query))
        except (AttributeError, KeyError):
            return str(url_for('search_archive',
                               searchtype='author',
                               archive=None, # TODO: This should be handled somehow
                               query=query))
    
    response_data['url_for_author_search'] = author_query

    return response_data, 200, {}