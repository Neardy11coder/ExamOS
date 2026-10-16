from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """SQLAlchemy DeclarativeBase for all ExamOS models."""
    pass


# Import all models here so that Alembic autogenerate can discover them
# via Base.metadata. Keep this list updated as new models are added.
import app.models  # noqa: E402, F401
