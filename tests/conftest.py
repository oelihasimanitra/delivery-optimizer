import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from deliveryopt.auth import hash_password  # noqa: E402
from deliveryopt.routing import EstimateProvider  # noqa: E402
from deliveryopt.server import AppContext, create_server  # noqa: E402
from deliveryopt.storage import Storage  # noqa: E402


@pytest.fixture()
def live_server(tmp_path):
    """Serveur réel sur un port libre, base SQLite temporaire, deux utilisateurs."""
    storage = Storage(tmp_path / "test.db")
    storage.add_user("admin", hash_password("motdepasse-admin"), "admin")
    storage.add_user("oper", hash_password("motdepasse-oper"), "operateur")
    ctx = AppContext(storage, EstimateProvider())
    server = create_server(ctx, "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    yield base, ctx
    server.shutdown()
    server.server_close()
