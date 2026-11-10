"""Password-format regression tests use synthetic values only; never Render secrets."""
import base64
import hashlib
import pytest
from atlas.auth import hash_password, parse_password_hash, settings, valid_hash, verify_password


def b64(value):
    return base64.b64encode(value).decode()


def sample_hash(salt=b's'*16, digest=b'd'*64):
    return 'scrypt$'+b64(salt)+'$'+b64(digest)


def test_documented_python_generation_matches_application():
    password='  synthetic chosen password é  '
    salt=bytes(range(16))
    digest=hashlib.scrypt(password.encode('utf-8'),salt=salt,n=32768,r=8,p=3,dklen=64,maxmem=64*1024*1024)
    encoded='scrypt$'+b64(salt)+'$'+b64(digest)
    assert valid_hash(encoded)
    assert parse_password_hash(encoded)==(salt,digest)
    assert verify_password(password,encoded)
    assert not verify_password(password.strip(),encoded)
    assert not verify_password('incorrect password',encoded)
    generated=hash_password(password)
    assert valid_hash(generated) and verify_password(password,generated)


def test_surrounding_environment_whitespace_is_consistent(monkeypatch):
    encoded=hash_password('synthetic password')
    monkeypatch.setenv('ATLAS_USERNAME',' \tconfigured-user\r\n')
    monkeypatch.setenv('ATLAS_PASSWORD_HASH',' \t'+encoded+'\r\n')
    _,username,normalized=settings()
    assert username=='configured-user'
    assert normalized==encoded
    assert valid_hash(' \n'+encoded+'\r\n')
    assert verify_password('synthetic password',' \n'+encoded+'\r\n')


@pytest.mark.parametrize('value,reason',[
    (None,'missing'),
    (' \n','empty_or_whitespace'),
    ('sensitive-marker','expected_scrypt_dollar'),
    ('scrypt$one$two$three','expected_scrypt_dollar'),
    ("'"+sample_hash()+"'",'surrounding_quotes_remove_quotes'),
    ('"'+sample_hash()+'"','surrounding_quotes_remove_quotes'),
    ('SCRYPT$'+b64(b's'*16)+'$'+b64(b'd'*64),'algorithm_must_be_scrypt'),
    ('scrypt$not base64!$'+b64(b'd'*64),'salt_invalid_standard_base64'),
    ('scrypt$'+b64(b's'*16)+'$not base64!','digest_invalid_standard_base64'),
    (sample_hash(salt=b's'*15),'salt_must_decode_to_16_bytes'),
    (sample_hash(digest=b'd'*32),'digest_must_decode_to_64_bytes'),
    ('scrypt$'+b64(b's'*16)+'$'+('dd'*64),'digest_must_decode_to_64_bytes'),
    ('scrypt$'+b64(b's'*16)+'$'+b64(b'd'*64)+'\nextra','digest_invalid_standard_base64'),
])
def test_precise_sanitized_hash_diagnostics(monkeypatch,capsys,value,reason):
    if value is None:
        monkeypatch.delenv('ATLAS_PASSWORD_HASH',raising=False)
    else:
        monkeypatch.setenv('ATLAS_PASSWORD_HASH',value)
    with pytest.raises(RuntimeError) as failure:
        settings()
    message=str(failure.value)
    assert 'ATLAS_PASSWORD_HASH: '+reason in message
    assert 'ATLAS_USERNAME:' not in message
    if value:
        assert value not in message
    assert 'sensitive-marker' not in message
    assert not valid_hash(value)
    output=capsys.readouterr()
    assert not output.out and not output.err


@pytest.mark.parametrize('value,reason',[(None,'missing'),(' \t\r\n','empty_or_whitespace')])
def test_username_diagnostics_do_not_echo_values(monkeypatch,value,reason):
    if value is None:monkeypatch.delenv('ATLAS_USERNAME',raising=False)
    else:monkeypatch.setenv('ATLAS_USERNAME',value)
    with pytest.raises(RuntimeError) as failure:settings()
    assert str(failure.value)=='Invalid ATLAS login configuration: ATLAS_USERNAME: '+reason


def test_both_missing_variables_reported(monkeypatch):
    monkeypatch.delenv('ATLAS_USERNAME',raising=False)
    monkeypatch.delenv('ATLAS_PASSWORD_HASH',raising=False)
    with pytest.raises(RuntimeError) as failure:settings()
    assert str(failure.value)=='Invalid ATLAS login configuration: ATLAS_USERNAME: missing; ATLAS_PASSWORD_HASH: missing'


def test_whitespace_wrapped_config_allows_real_login(tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    from atlas import main
    from atlas.storage import init_db
    monkeypatch.setattr(main,'Session',init_db(f'sqlite:///{tmp_path}/login.db'))
    encoded=hash_password('synthetic login password')
    monkeypatch.setenv('ATLAS_USERNAME','  login-user\n')
    monkeypatch.setenv('ATLAS_PASSWORD_HASH','\n'+encoded+'\n')
    with TestClient(main.app) as client:
        response=client.post('/auth/login',data={'username':'login-user','password':'synthetic login password'},headers={'Origin':'http://127.0.0.1:5173'},follow_redirects=False)
        assert response.status_code==303
        assert client.get('/api/catalog').status_code==200
