import os
import tempfile
import pytest

# Never initialize the application against a developer/cloud database during tests.
_test_data = tempfile.TemporaryDirectory(prefix="atlas-tests-")
os.environ.pop("DATABASE_URL", None)
os.environ["ATLAS_DATA_DIR"] = _test_data.name
from atlas.auth import hash_password

@pytest.fixture(autouse=True)
def auth_environment(monkeypatch):
 monkeypatch.setenv('ATLAS_USERNAME','tester')
 monkeypatch.setenv('ATLAS_PASSWORD_HASH',hash_password('test-password-long'))
 monkeypatch.setenv('APP_ORIGIN','http://127.0.0.1:5173')
 monkeypatch.delenv('ATLAS_ENV',raising=False)
 monkeypatch.delenv('RENDER',raising=False)
