import os
from flask import Blueprint, current_app, send_from_directory

bp = Blueprint("files", __name__)

# @bp.get("/uploads/<path:filename>")
# def uploaded_file(filename):
#     # upload_dir = current_app.config["UPLOAD_DIR"]
#     return send_from_directory(upload_dir, filename)
