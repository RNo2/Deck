"""Exercise the physical DBAPI connection hook without contacting a database."""
import socket
from unittest.mock import Mock
import pytest
from atlas.storage import make_engine


class ConnectionCaptured(Exception):
    pass


def postgres_engine(monkeypatch, query='sslmode=verify-full'):
    engine = make_engine('postgresql://fixture-user:fixture-password@db.example:5433/fixture-db?'+query)
    connect = Mock(side_effect=ConnectionCaptured)
    monkeypatch.setattr(engine.dialect.loaded_dbapi, 'connect', connect)
    return engine, connect


def address(ip):
    return (socket.AF_INET, socket.SOCK_STREAM, 6, '', (ip, 5433))


def test_ipv4_connection_preserves_hostname_tls_and_credentials(monkeypatch):
    engine, connect = postgres_engine(monkeypatch)
    resolve = Mock(return_value=[address('192.0.2.10'), address('192.0.2.11')])
    monkeypatch.setattr(socket, 'getaddrinfo', resolve)
    try:
        with pytest.raises(ConnectionCaptured):
            engine.connect()
        resolve.assert_called_once_with('db.example', 5433, socket.AF_INET, socket.SOCK_STREAM)
        params = connect.call_args.kwargs
        assert params['hostaddr'] == '192.0.2.10'
        assert params['host'] == 'db.example'
        assert params['sslmode'] == 'verify-full'
        assert params['sslrootcert'] == 'system'
        assert params['user'] == 'fixture-user'
        assert params['password'] == 'fixture-password'
        assert params['dbname'] == 'fixture-db'
        assert params['port'] == 5433
    finally:
        engine.dispose()


def test_new_connections_resolve_fresh_addresses(monkeypatch):
    engine, connect = postgres_engine(monkeypatch)
    resolve = Mock(side_effect=[[address('192.0.2.10')], [address('192.0.2.20')]])
    monkeypatch.setattr(socket, 'getaddrinfo', resolve)
    try:
        for _ in range(2):
            with pytest.raises(ConnectionCaptured):
                engine.connect()
        assert resolve.call_count == 2
        assert [call.kwargs['hostaddr'] for call in connect.call_args_list] == ['192.0.2.10', '192.0.2.20']
    finally:
        engine.dispose()


@pytest.mark.parametrize('result,message', [
    ([], 'no IPv4 addresses'),
    (socket.gaierror(socket.EAI_NONAME, 'sensitive resolver detail'), 'IPv4 resolution failed'),
])
def test_ipv4_resolution_failure_is_clear_and_prevents_connection(monkeypatch, result, message):
    engine, connect = postgres_engine(monkeypatch)
    resolve = Mock(side_effect=result) if isinstance(result, Exception) else Mock(return_value=result)
    monkeypatch.setattr(socket, 'getaddrinfo', resolve)
    try:
        with pytest.raises(RuntimeError, match=message) as failure:
            engine.connect()
        assert 'sensitive' not in str(failure.value)
        assert 'fixture-password' not in str(failure.value)
        connect.assert_not_called()
    finally:
        engine.dispose()


def test_explicit_tls_root_and_options_unchanged(monkeypatch):
    engine, connect = postgres_engine(monkeypatch,'sslmode=verify-full&sslrootcert=/custom/roots.pem&channel_binding=require&connect_timeout=7')
    monkeypatch.setattr(socket, 'getaddrinfo', Mock(return_value=[address('192.0.2.10')]))
    try:
        with pytest.raises(ConnectionCaptured):
            engine.connect()
        params=connect.call_args.kwargs
        assert params['sslrootcert']=='/custom/roots.pem'
        assert params['sslmode']=='verify-full'
        assert params['channel_binding']=='require'
        assert params['connect_timeout']=='7'
    finally:
        engine.dispose()


def test_sqlite_never_resolves_or_changes_connection_behavior(monkeypatch):
    resolve = Mock(side_effect=AssertionError('SQLite must not resolve DNS'))
    monkeypatch.setattr(socket, 'getaddrinfo', resolve)
    engine = make_engine('sqlite:///:memory:')
    try:
        with engine.connect() as connection:
            assert connection.exec_driver_sql('SELECT 1').scalar() == 1
        resolve.assert_not_called()
    finally:
        engine.dispose()
