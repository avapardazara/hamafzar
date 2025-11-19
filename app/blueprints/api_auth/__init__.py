from flask import Blueprint
api_auth_bp = Blueprint("api_auth", __name__)
from . import routes  # noqa
