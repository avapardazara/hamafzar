# -*- coding: utf-8 -*-
# دستورات CLI برای صدور/لیست/لغو توکن‌ها
import click
from datetime import datetime, timedelta
from app.extensions import db
from app.models.api_token import ApiToken
from app.security.tokens import create_api_token
from app.models.user import User  # فرض: مدل User موجود است

def register_cli(app):
    @app.cli.command("issue-token")
    @click.option("--user-id", type=int, help="شناسه‌ی کاربر")
    @click.option("--email", type=str, help="ایمیل کاربر (جایگزین user-id)")
    @click.option("--label", type=str, default="manual", help="برچسب توکن")
    @click.option("--days", type=int, default=90, help="انقضا به روز (0 = بدون انقضا)")
    def issue_token(user_id, email, label, days):
        """صدور یک توکن جدید و نمایش متن خام (فقط یک‌بار)."""
        if not user_id and not email:
            click.echo("یکی از --user-id یا --email لازم است.")
            return
        user = None
        if user_id:
            user = User.query.get(user_id)
        elif email:
            user = User.query.filter_by(email=email).first()
        if not user:
            click.echo("کاربر پیدا نشد.")
            return
        expires_at = None
        if days and days > 0:
            expires_at = datetime.utcnow() + timedelta(days=days)
        token_plain, tok = create_api_token(user, label=label, expires_at=expires_at)
        click.echo("== توکن شما (فقط همین بار نمایش داده می‌شود) ==")
        click.echo(token_plain)
        click.echo(f"token_id={tok.id} user_id={user.id} expires_at={expires_at}")

    @app.cli.command("revoke-token")
    @click.option("--token-id", type=int, required=True)
    def revoke_token(token_id):
        tok = ApiToken.query.get(token_id)
        if not tok:
            click.echo("توکن پیدا نشد.")
            return
        tok.revoked_at = datetime.utcnow()
        db.session.commit()
        click.echo(f"توکن {token_id} لغو شد.")

    @app.cli.command("list-tokens")
    @click.option("--user-id", type=int, required=True)
    def list_tokens(user_id):
        qs = ApiToken.query.filter_by(user_id=user_id).order_by(ApiToken.created_at.desc())
        for t in qs:
            click.echo(f"id={t.id} label={t.label} active={t.is_active()} expires_at={t.expires_at} revoked_at={t.revoked_at}")
