from flask import request
from flask_restx import fields, reqparse

MAX_PER_PAGE = 100


def pagination_parser():
    parser = reqparse.RequestParser()
    parser.add_argument("page", type=int, default=1, location="args")
    parser.add_argument("per_page", type=int, default=25, location="args", help=f"Max {MAX_PER_PAGE}")
    return parser


def paginate(db, stmt, page, per_page):
    page = max(page or 1, 1)
    per_page = min(max(per_page or 25, 1), MAX_PER_PAGE)
    result = db.paginate(stmt, page=page, per_page=per_page, error_out=False)
    return {
        "items": result.items,
        "total": result.total,
        "page": result.page,
        "per_page": result.per_page,
        "pages": result.pages,
    }


def page_model(ns, name, item_model):
    return ns.model(
        name,
        {
            "items": fields.List(fields.Nested(item_model)),
            "total": fields.Integer,
            "page": fields.Integer,
            "per_page": fields.Integer,
            "pages": fields.Integer,
        },
    )


def json_body(ns):
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        ns.abort(400, "Request body must be a JSON object")
    return payload
