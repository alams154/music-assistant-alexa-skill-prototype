"""Package for endpoint blueprints.

Import and export blueprint objects so `app.app` can register them.
"""

from .status import status_bp
from .invocations import invocations_bp

__all__ = [
    'status_bp',
    'invocations_bp',
]
