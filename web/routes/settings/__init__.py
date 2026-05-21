from flask import Blueprint

bp = Blueprint("settings", __name__, url_prefix="/settings")

# Import submodules to register their routes onto bp.
# Order matters: _auth before _sync (sync imports auth constants).
from . import _auth, _sync, _backup, _config  # noqa: F401, E402

from ._sync import start_auto_sync_scheduler  # noqa: E402
from ._backup import start_backup_scheduler  # noqa: E402

__all__ = ["bp", "start_auto_sync_scheduler", "start_backup_scheduler"]
