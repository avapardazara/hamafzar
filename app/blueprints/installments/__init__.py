from flask import Blueprint

bp = Blueprint("installments", __name__, url_prefix="/installments")

from . import routes  # noqa
