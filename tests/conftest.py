import pytest
from fastapi.testclient import TestClient

from app.main import crear_app


@pytest.fixture(scope="session")
def cliente():
    # El bloque `with` ejecuta el ciclo de vida: carga y verificación del modelo.
    with TestClient(crear_app()) as c:
        yield c
