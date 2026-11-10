"""Single-user, database-backed opaque sessions. No credentials in source or cookies."""
import base64
import getpass
import hashlib
import hmac
import os
import secrets
import time
from urllib.parse import parse_qs, urlsplit
from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import delete
from .storage import LoginSession, LoginThrottle

COOKIE="atlas_session"
TTL=8*60*60

def hash_password(password):
 salt=secrets.token_bytes(16)
 digest=hashlib.scrypt(password.encode(),salt=salt,n=32768,r=8,p=3,maxmem=64*1024*1024)
 return "scrypt$"+base64.b64encode(salt).decode()+"$"+base64.b64encode(digest).decode()

def parse_password_hash(value):
 # Only surrounding environment-value whitespace is normalized. Never trim passwords.
 # Error messages are fixed codes: no supplied values, hashes or decoded bytes.
 if value is None:
  raise ValueError("missing")
 if not isinstance(value,str):
  raise ValueError("expected_string")
 value=value.strip()
 if not value:
  raise ValueError("empty_or_whitespace")
 if value.startswith(("'",'"')) or value.endswith(("'",'"')):
  raise ValueError("surrounding_quotes_remove_quotes")
 parts=value.split("$")
 if len(parts)!=3:
  raise ValueError("expected_scrypt_dollar_base64salt_dollar_base64digest")
 kind,salt,digest=parts
 if kind!="scrypt":
  raise ValueError("algorithm_must_be_scrypt")
 decoded=[]
 for name,encoded,size in (("salt",salt,16),("digest",digest,64)):
  try:
   raw=base64.b64decode(encoded,validate=True)
  except (ValueError,TypeError):
   raise ValueError(name+"_invalid_standard_base64") from None
  if len(raw)!=size:
   raise ValueError(name+"_must_decode_to_"+str(size)+"_bytes")
  decoded.append(raw)
 return decoded[0],decoded[1]

def valid_hash(value):
 try:
  parse_password_hash(value)
  return True
 except ValueError:
  return False

def verify_password(password, encoded):
 salt,digest=parse_password_hash(encoded)
 actual=hashlib.scrypt(password.encode(),salt=salt,n=32768,r=8,p=3,maxmem=64*1024*1024)
 return hmac.compare_digest(actual,digest)

def settings():
 origin=os.environ.get("APP_ORIGIN", "http://127.0.0.1:5173").rstrip("/")
 parsed=urlsplit(origin)
 if parsed.scheme not in ("http","https") or not parsed.netloc or parsed.path or parsed.query or parsed.fragment or parsed.username:
  raise RuntimeError("APP_ORIGIN must be an absolute origin without path or credentials")
 production=os.environ.get("ATLAS_ENV")=="production" or bool(os.environ.get("RENDER"))
 if production and (parsed.scheme!="https" or not os.environ.get("DATABASE_URL","").startswith(("postgres://","postgresql://","postgresql+psycopg://"))):
  raise RuntimeError("Production requires HTTPS APP_ORIGIN and PostgreSQL DATABASE_URL")
 username_raw=os.environ.get("ATLAS_USERNAME")
 password_hash_raw=os.environ.get("ATLAS_PASSWORD_HASH")
 username=(username_raw or "").strip()
 password_hash=(password_hash_raw or "").strip()
 issues=[]
 if not username:
  issues.append("ATLAS_USERNAME: "+("missing" if username_raw is None else "empty_or_whitespace"))
 try:
  parse_password_hash(password_hash_raw)
 except ValueError as exc:
  issues.append("ATLAS_PASSWORD_HASH: "+str(exc))
 if issues:
  raise RuntimeError("Invalid ATLAS login configuration: "+"; ".join(issues)) from None
 return origin,username,password_hash

def digest(token): return hashlib.sha256(token.encode()).hexdigest()

def install_auth(app, session_factory):
 @app.middleware("http")
 async def protect(request, call_next):
  origin,username,password_hash=settings()
  unsafe=request.method not in ("GET","HEAD","OPTIONS")
  # Exact Origin validation for browser forms; custom headers for same-origin API calls.
  if unsafe and (request.headers.get("origin") not in (None,origin) or request.headers.get("sec-fetch-site")=="cross-site"):
   return JSONResponse({"detail":"Cross-origin request rejected"},status_code=403)
  if unsafe and request.url.path!="/auth/login" and request.headers.get("X-ATLAS-CSRF")!="1":
   return JSONResponse({"detail":"CSRF header required"},status_code=403)
  if unsafe and request.url.path=="/auth/login" and request.headers.get("origin")!=origin:
   return JSONResponse({"detail":"Login Origin required"},status_code=403)
  public=request.url.path in ("/api/health","/auth/login")
  if not public:
   token=request.cookies.get(COOKIE,"")
   with session_factory()() as s:
    record=s.get(LoginSession,digest(token)) if token else None
    authenticated=record is not None and record.expires>int(time.time()) and hmac.compare_digest(record.credential_tag,digest(username+password_hash))
   if not authenticated:
    response=JSONResponse({"detail":"Authentication required"},status_code=401) if request.url.path.startswith('/api/') else RedirectResponse('/auth/login',status_code=303)
   else: response=await call_next(request)
  else: response=await call_next(request)
  response.headers["Cache-Control"]="no-store"
  response.headers["X-Content-Type-Options"]="nosniff"
  response.headers["X-Frame-Options"]="DENY"
  response.headers["Referrer-Policy"]="same-origin"
  response.headers.setdefault("Content-Security-Policy","default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; form-action 'self'; base-uri 'none'")
  if origin.startswith("https://"): response.headers["Strict-Transport-Security"]="max-age=31536000"
  return response

 @app.get("/auth/login",response_class=HTMLResponse)
 def login_page():
  return HTMLResponse('''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>ATLAS · Sign in</title><style>body{background:#101412;color:#d9dfda;font:16px system-ui;max-width:340px;margin:15vh auto;padding:20px}label{display:block;margin:22px 0}input{display:block;box-sizing:border-box;width:100%;margin-top:8px;padding:12px;background:#172019;color:inherit;border:1px solid #53695a}button{padding:12px 24px;background:#9fbaa7;border:0}p{color:#9eafa3}</style><h1>ATLAS</h1><p>Private research workspace</p><form method="post" action="/auth/login"><label>Username<input name="username" autocomplete="username" required maxlength="200"></label><label>Password<input name="password" type="password" autocomplete="current-password" required maxlength="1024"></label><button>Sign in</button></form></html>''')

 @app.post("/auth/login")
 async def login(request: Request):
  origin,username,password_hash=settings()
  raw=bytearray()
  async for chunk in request.stream():
   raw.extend(chunk)
   if len(raw)>8192: return JSONResponse({"detail":"Login request too large"},status_code=413)
  fields=parse_qs(raw.decode("utf-8",errors="replace"))
  supplied_user=fields.get("username",[""])[0]
  supplied_password=fields.get("password",[""])[0]
  if len(supplied_password)>1024: return JSONResponse({"detail":"Invalid credentials"},status_code=401)
  # A single row lock serializes attempts across workers and process restarts.
  with session_factory()() as s:
   from sqlalchemy import select
   throttle=s.scalar(select(LoginThrottle).where(LoginThrottle.id==1).with_for_update())
   now=int(time.time())
   if now-throttle.window_start>=900:
    throttle.failures=0; throttle.window_start=now
   if throttle.failures>=5:
    s.commit()
    return JSONResponse({"detail":"Too many attempts; retry after 15 minutes"},status_code=429)
   correct=verify_password(supplied_password,password_hash)
   if not (hmac.compare_digest(supplied_user.encode(),username.encode()) and correct):
    throttle.failures+=1;s.commit()
    return JSONResponse({"detail":"Invalid credentials"},status_code=401)
   throttle.failures=0
   s.execute(delete(LoginSession).where(LoginSession.expires<=now))
   old=request.cookies.get(COOKIE)
   if old: s.execute(delete(LoginSession).where(LoginSession.token_hash==digest(old)))
   token=secrets.token_urlsafe(32)
   s.add(LoginSession(token_hash=digest(token),expires=now+TTL,credential_tag=digest(username+password_hash)))
   s.commit()
  response=RedirectResponse('/',status_code=303)
  response.set_cookie(COOKIE,token,max_age=TTL,httponly=True,secure=origin.startswith('https://'),samesite='strict',path='/')
  return response

 @app.post("/auth/logout")
 def logout(request: Request):
  with session_factory()() as s:
   s.execute(delete(LoginSession).where(LoginSession.token_hash==digest(request.cookies.get(COOKIE,''))));s.commit()
  response=JSONResponse({"signed_out":True});response.delete_cookie(COOKIE,path='/')
  return response

if __name__=="__main__":
 password=getpass.getpass("Password (at least 12 characters): ")
 if len(password)<12: raise SystemExit("Use at least 12 characters")
 if password!=getpass.getpass("Confirm password: "): raise SystemExit("Passwords differ")
 print(hash_password(password))
