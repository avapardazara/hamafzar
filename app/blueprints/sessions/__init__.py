from flask import Blueprint
from . import routes
bp = Blueprint("sessions", __name__, url_prefix="/sessions")

