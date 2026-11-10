import errno
import json
import socket
import subprocess
from unittest.mock import MagicMock
import pytest
from atlas import network_diagnostic as diagnostic


def events(capsys):
    return [json.loads(line) for line in capsys.readouterr().out.splitlines()]


def test_target_credentials_never_logged(monkeypatch, capsys):
    monkeypatch.setenv('DATABASE_URL', 'postgresql+psycopg://private-user:private-password@db.example:5433/private-db?secret=private-query')
    monkeypatch.setattr(diagnostic.socket, 'getaddrinfo', lambda *args: [])
    assert diagnostic.target() == ('db.example', 5433)
    diagnostic.probe()
    output = capsys.readouterr().out
    for secret in ('private-user', 'private-password', 'private-db', 'private-query', 'db.example'):
        assert secret not in output
    assert '5433' in output


@pytest.mark.parametrize('family,label,address', [
    (socket.AF_INET, 'IPv4', ('192.0.2.1', 5432)),
    (socket.AF_INET6, 'IPv6', ('2001:db8::1', 5432, 0, 0)),
])
def test_each_family_uses_its_own_socket(monkeypatch, capsys, family, label, address):
    resolve = MagicMock(return_value=[(family, socket.SOCK_STREAM, 6, '', address)])
    create = MagicMock()
    monkeypatch.setattr(diagnostic.socket, 'getaddrinfo', resolve)
    monkeypatch.setattr(diagnostic.socket, 'socket', create)
    diagnostic.probe_family('db.example', 5432, family, label)
    resolve.assert_called_once_with('db.example', 5432, family, socket.SOCK_STREAM)
    create.assert_called_once_with(family, socket.SOCK_STREAM)
    create.return_value.__enter__.return_value.connect.assert_called_once_with(address)
    assert events(capsys)[-1]['status'] == 'reachable'


def test_dns_error_sanitized(monkeypatch, capsys):
    def fail(*args):
        raise socket.gaierror(socket.EAI_AGAIN, 'credential-must-not-appear')
    monkeypatch.setattr(diagnostic.socket, 'getaddrinfo', fail)
    diagnostic.probe_family('db.example', 5432, socket.AF_INET, 'IPv4')
    assert events(capsys) == [{'diagnostic':'postgres_network', 'event':'dns', 'family':'IPv4', 'status':'failed', 'code':socket.EAI_AGAIN}]


def test_tcp_error_sanitized(monkeypatch, capsys):
    monkeypatch.setattr(diagnostic.socket, 'getaddrinfo', lambda *a:[(socket.AF_INET6, socket.SOCK_STREAM, 6, '', ('2001:db8::1',5432,0,0))])
    create=MagicMock()
    create.return_value.__enter__.return_value.connect.side_effect=OSError(errno.ENETUNREACH,'credential-must-not-appear')
    monkeypatch.setattr(diagnostic.socket,'socket',create)
    diagnostic.probe_family('db.example',5432,socket.AF_INET6,'IPv6')
    event=events(capsys)[-1]
    assert event['code']=='ENETUNREACH' and event['status']=='failed'


def test_total_timeout_does_not_fail_startup(monkeypatch, capsys):
    run=MagicMock(side_effect=subprocess.TimeoutExpired('command',25))
    monkeypatch.setattr(diagnostic.subprocess,'run',run)
    diagnostic.main()
    assert events(capsys)[0]['event']=='timeout'
    assert run.call_args.kwargs['timeout']==25
    assert all('postgresql://' not in arg for arg in run.call_args.args[0])


def test_invalid_url_does_not_expose_input(monkeypatch, capsys):
    monkeypatch.setenv('DATABASE_URL','postgresql://user:secret@db.example:secret-port/db')
    diagnostic.probe()
    assert events(capsys)[0]['status']=='invalid_database_url'


def test_render_diagnostic_precedes_migration():
    from pathlib import Path
    config=(Path(__file__).resolve().parents[2]/'render.yaml').read_text()
    assert config.index('python -m atlas.network_diagnostic') < config.index('python -m atlas.migrate')
