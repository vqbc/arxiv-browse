"""Routes for PDF, source and other downloads."""
import logging
from email.utils import format_datetime

from arxiv.identifier import Identifier, IdentifierException
from browse.services.dissemination import formats, get_article_store
from browse.services.dissemination.article_store import CannotBuildPdf, Deleted
from browse.services.dissemination.fileobj import FileObj
from browse.services.dissemination.next_published import next_publish
from flask import Blueprint, abort, redirect, render_template, url_for
from flask_rangerequest import RangeRequest
from opentelemetry import trace



logger = logging.getLogger(__file__)
logger.setLevel(logging.INFO)

blueprint = Blueprint('dissemination', __name__)

tracer = trace.get_tracer(__name__)


@blueprint.route("/pdf/<string:archive>/<string:arxiv_id>", methods=['GET', 'HEAD'])
@blueprint.route("/pdf/<string:arxiv_id>", methods=['GET', 'HEAD'])
def redirect_pdf(arxiv_id: str, archive=None):  # type: ignore
    """Redirect urls without .pdf so they download a filename recognized as a PDF."""
    arxiv_id = f"{archive}/{arxiv_id}" if archive else arxiv_id
    return redirect(url_for('.pdf', arxiv_id=arxiv_id, _external=True), 301)


@blueprint.route("/pdf/<string:archive>/<string:arxiv_id>.pdf", methods=['GET', 'HEAD'])
@blueprint.route("/pdf/<string:arxiv_id>.pdf", methods=['GET', 'HEAD'])
def pdf(arxiv_id: str, archive=None):  # type: ignore
    """Want to handle the following patterns:

        /pdf/{archive}/{id}v{v}
        /pdf/{archive}/{id}v{v}.pdf
        /pdf/{id}v{v}
        /pdf/{id}v{v}.pdf

    The dissemination service does not handle versionless
    requests. The version should be figured out in some other service
    and redirected to the CDN.

    Serve these from storage bucket URLs like:

    gs://arxiv-production-data/ps_cache/acc-phys/pdf/9502/9502001v1.pdf

    Does a 400 if the ID is malformed or lacks a version.

    Does a 404 if the key for the ID does not exist on the bucket.
    """
    arxiv_id = f"{archive}/{arxiv_id}" if archive else arxiv_id
    try:
        if len(arxiv_id) > 40:
            abort(400)
        if arxiv_id.startswith('arxiv/'):
            abort(400, description="do not prefix with arxiv/ for non-legacy ids")
        id = Identifier(arxiv_id)
    except IdentifierException as ex:
        return bad_id(arxiv_id, str(ex))

    item = get_article_store().dissemination(formats.pdf, id)
    logger. debug(f"dissemination_for_id({id.idv}) was {item}")
    if not item or item == "VERSION_NOT_FOUND" or item == "ARTICLE_NOT_FOUND":
        return not_found(arxiv_id)
    elif item in ["WITHDRAWN", "NO_SOURCE"]:
        return withdrawn(arxiv_id)
    elif item == "UNAVAIABLE":
        return unavailable(arxiv_id)
    elif item == "NOT_PDF":
        return not_pdf(arxiv_id)
    elif isinstance(item, Deleted):
        return bad_id(arxiv_id, item.msg)
    elif isinstance(item, CannotBuildPdf):
        return cannot_build_pdf(arxiv_id, item.msg)
    elif not item or not item.exists():  # type: ignore
        return not_found(arxiv_id)

    file: FileObj = item  # type: ignore
    resp = RangeRequest(file.open('rb'),
                        etag=file.etag,
                        last_modified=file.updated,
                        size=file.size).make_response()

    resp.headers['Access-Control-Allow-Origin'] = '*'
    resp.headers['Content-Type'] = 'application/pdf'

    if resp.status_code == 200:
        # To do Large PDFs on Cloud Run both chunked and no content-length are needed
        resp.headers['Transfer-Encoding'] = 'chunked'
        resp.headers.pop('Content-Length')

    if id.has_version:
        resp.headers['Cache-Control'] = _cc_versioned()
    else:
        resp.headers['Expires'] = format_datetime(next_publish())
    return resp


def _cc_versioned():  # type: ignore
    """Versioned pdfs should not change so let's put a time a bit in the future.
    Non versioned could change during the next publish."""
    return 'max-age=604800' # 7 days

def withdrawn(arxiv_id: str):  # type: ignore
    headers = {'Cache-Cache': 'max-age=31536000'} # one year, max allowed by RFC 2616
    return render_template("pdf/withdrawn.html", arxiv_id=arxiv_id), 200, headers

def unavailable(arxiv_id: str):  # type: ignore
    return render_template("pdf/unavaiable.html", arxiv_id=arxiv_id), 500, {}

def not_pdf(arxiv_id: str):  # type: ignore
    return render_template("pdf/unavaiable.html", arxiv_id=arxiv_id), 404, {}

def not_found(arxiv_id: str):  # type: ignore
    headers = {'Expires': format_datetime(next_publish())}
    return render_template("pdf/not_found.html", arxiv_id=arxiv_id), 404, headers

def bad_id( arxiv_id: str, err_msg: str):  # type: ignore
    return render_template("pdf/bad_id.html", err_msg=err_msg, arxiv_id=arxiv_id), 404, {}

def cannot_build_pdf(arxiv_id: str, msg: str):  # type: ignore
    return render_template("pdf/cannot_build_pdf.html", err_msg=msg,  arxiv_id=arxiv_id), 404, {}