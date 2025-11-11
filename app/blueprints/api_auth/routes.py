from flask import request
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity
from . import api_auth_bp
from ...extensions import db
from ...models.user import User

@api_auth_bp.post("/login")
def login():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    if not username or not password:
        return {"message": "username & password required"}, 400

    user = User.query.filter_by(username=username).first()
    if not user or not user.check_password(password) or not user.is_active:
        return {"message": "Invalid credentials"}, 401

    token = create_access_token(identity={"id": user.id, "username": user.username})
    return {"access_token": token, "user": user.to_dict()}

@api_auth_bp.get("/me")
@jwt_required()
def me():
    ident = get_jwt_identity() or {}
    user = User.query.filter_by(username=ident.get("username")).first()
    if not user:
        return {"message": "User not found"}, 404
    return {"user": user.to_dict()}
