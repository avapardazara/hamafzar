from __future__ import with_statement
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool
from flask import current_app

# Alembic Config
config = context.config

# Logging (در صورت داشتن تنظیمات در alembic.ini)
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# متادیتا از Flask-Migrate
target_metadata = current_app.extensions['migrate'].db.metadata

def _set_sqlalchemy_url_from_app():
    """URL دیتابیس را از Flask بگیر، مسیر sqlite را نرمال کن، و پوشه را بساز."""
    uri = str(current_app.config.get("SQLALCHEMY_DATABASE_URI"))

    if uri.startswith("sqlite:///"):
        path = uri.replace("sqlite:///", "", 1).replace("\\", "/")
        db_dir = os.path.dirname(path)
        if db_dir and not os.path.isdir(db_dir):
            os.makedirs(db_dir, exist_ok=True)
        uri = "sqlite:///" + path  # نرمال‌شده با /

    config.set_main_option("sqlalchemy.url", uri)

def run_migrations_offline() -> None:
    _set_sqlalchemy_url_from_app()
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online() -> None:
    _set_sqlalchemy_url_from_app()  # همون تابعی که قبلاً گذاشتیم تا URL رو از Flask بگیره و پوشه sqlite رو بسازه

    from sqlalchemy.engine.url import make_url
    url = make_url(context.config.get_main_option("sqlalchemy.url"))
    is_sqlite = (url.get_backend_name() == "sqlite")

    connectable = engine_from_config(
        context.config.get_section(context.config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            render_as_batch=is_sqlite,  # ← این خط مهمه برای SQLite
        )
        with context.begin_transaction():
            context.run_migrations()
