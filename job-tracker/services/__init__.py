"""Package exposing our service blueprints."""

from .health import health_bp
from .db import db_bp
from .submit import submit_bp
from .jobs import jobs_bp
from .profiles import profiles_bp
from .applications import applications_bp
from .interview_prep import interview_prep_bp

__all__ = [
    "health_bp",
    "db_bp",
    "submit_bp",
    "jobs_bp",
    "profiles_bp",
    "applications_bp",
    "interview_prep_bp",
]
