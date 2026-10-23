import os, hmac, hashlib, secrets, time, math, json
from datetime import date, datetime, timezone
from typing import Optional
from fastapi import FastAPI, Depends, HTTPException, Header, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import create_engine, String, Integer, Float, Boolean, Date, DateTime, Text, ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker, Session

DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///./vibe.db')
TOKEN_SECRET = os.getenv('TOKEN_SECRET', 'CHANGE_THIS_TO_A_LONG_RANDOM_SECRET_BEFORE_DEPLOYING')
if TOKEN_SECRET == 'CHANGE_THIS_TO_A_LONG_RANDOM_SECRET_BEFORE_DEPLOYING':
    print('WARNING: using development TOKEN_SECRET. Set TOKEN_SECRET before deployment.')
engine = create_engine(DATABASE_URL, connect_args={'check_same_thread': False} if DATABASE_URL.startswith('sqlite') else {}, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

class Base(DeclarativeBase): pass
class User(Base):
    __tablename__ = 'users'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    birth_date: Mapped[date] = mapped_column(Date)
    intent: Mapped[str] = mapped_column(String(40), default='Just talk')
    vibes_json: Mapped[str] = mapped_column(Text, default='[]')
    radius_km: Mapped[int] = mapped_column(Integer, default=5)
    available: Mapped[bool] = mapped_column(Boolean, default=False)
    location_consent: Mapped[bool] = mapped_column(Boolean, default=False)
    latitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    longitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    last_seen: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    active_match_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class Match(Base):
    __tablename__ = 'matches'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_a: Mapped[int] = mapped_column(ForeignKey('users.id'))
    user_b: Mapped[int] = mapped_column(ForeignKey('users.id'))
    status: Mapped[str] = mapped_column(String(20), default='active')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class ChatMessage(Base):
    __tablename__ = 'chat_messages'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey('matches.id'), index=True)
    sender_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    content: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class UserBlock(Base):
    __tablename__ = 'user_blocks'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    blocker_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    blocked_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class UserReport(Base):
    __tablename__ = 'user_reports'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reporter_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    reported_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    match_id: Mapped[int] = mapped_column(ForeignKey('matches.id'), index=True)
    reason: Mapped[str] = mapped_column(String(40))
    details: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

# In-memory WebSocket connections are suitable for one local development server only.
chat_connections: dict[int, dict[WebSocket, int]] = {}

Base.metadata.create_all(bind=engine)
app = FastAPI(title='Vibe API', version='0.2.0', description='Stage 3: accounts, nearby matching, and real-time anonymous chat')
app.add_middleware(CORSMiddleware, allow_origins=os.getenv('CORS_ORIGINS', 'http://127.0.0.1:5500,http://localhost:5500').split(','), allow_credentials=False, allow_methods=['GET','POST','PATCH','DELETE','OPTIONS'], allow_headers=['Authorization','Content-Type'])

def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)
    birth_date: date
class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)
class PrefsIn(BaseModel):
    intent: str = Field(pattern='^(Just talk|Find a buddy|Casual dating|Meet a group)$')
    vibes: list[str] = Field(default_factory=list, max_length=8)
    radius_km: int = Field(default=5, ge=1, le=25)
class LocationIn(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    consent: bool

# Passwords use Python's scrypt KDF; bearer tokens are signed and expire after 12 hours.
def hash_password(password: str, salt: Optional[bytes] = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return salt.hex() + ':' + digest.hex()
def verify_password(password: str, stored: str) -> bool:
    try:
        salt_hex, digest_hex = stored.split(':', 1)
        actual = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex), n=2**14, r=8, p=1, dklen=32)
        return hmac.compare_digest(actual.hex(), digest_hex)
    except Exception: return False
def make_token(user_id: int) -> str:
    payload = f'{user_id}:{int(time.time()) + 43200}'
    sig = hmac.new(TOKEN_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return payload + ':' + sig
def read_token(token: str) -> int:
    try:
        user_text, exp_text, sig = token.split(':', 2)
        payload = f'{user_text}:{exp_text}'
        expected = hmac.new(TOKEN_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected) or int(exp_text) < int(time.time()): raise ValueError()
        return int(user_text)
    except Exception: raise HTTPException(401, 'Session expired or invalid. Please sign in again.')
def current_user(authorization: Optional[str] = Header(default=None), db: Session = Depends(get_db)) -> User:
    if not authorization or not authorization.startswith('Bearer '): raise HTTPException(401, 'Sign in to continue.')
    user = db.get(User, read_token(authorization[7:]))
    if not user: raise HTTPException(401, 'Account not found. Please sign in again.')
    return user
def age_on_today(born: date) -> int:
    today = date.today()
    return today.year - born.year - ((today.month, today.day) < (born.month, born.day))
def public_state(user: User):
    # Never return email, birth date, exact coordinates, password hash, or account ID.
    return {'intent': user.intent, 'vibes': json.loads(user.vibes_json), 'radius_km': user.radius_km, 'available': user.available, 'location_enabled': user.location_consent}
def distance_km(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2-lat1), math.radians(lon2-lon1)
    a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2*r*math.asin(min(1, math.sqrt(a)))
def match_compatible(a: User, b: User, db: Session) -> bool:
    if a.id == b.id or not b.available or not b.location_consent or b.latitude is None or b.longitude is None: return False
    if b.active_match_id is not None: return False
    if a.intent != b.intent: return False
    # A person must fit within both users' selected radius.
    dist = distance_km(a.latitude, a.longitude, b.latitude, b.longitude)
    if dist > min(a.radius_km, b.radius_km): return False
    av, bv = set(json.loads(a.vibes_json)), set(json.loads(b.vibes_json))
    return not av or not bv or bool(av & bv)

@app.get('/')
def root(): return {'name':'Vibe API','stage':2,'status':'running'}
@app.get('/health')
def health(): return {'status':'ok'}
@app.post('/auth/register')
def register(payload: RegisterIn, db: Session = Depends(get_db)):
    if age_on_today(payload.birth_date) < 18: raise HTTPException(403, 'Vibe is currently for adults aged 18 and over.')
    if payload.birth_date > date.today(): raise HTTPException(400, 'Birth date cannot be in the future.')
    email = str(payload.email).lower().strip()
    if db.query(User).filter(User.email == email).first(): raise HTTPException(409, 'An account with this email already exists.')
    user = User(email=email, password_hash=hash_password(payload.password), birth_date=payload.birth_date)
    db.add(user); db.commit(); db.refresh(user)
    return {'access_token': make_token(user.id), 'token_type':'bearer', 'user': public_state(user)}
@app.post('/auth/login')
def login(payload: LoginIn, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == str(payload.email).lower().strip()).first()
    if not user or not verify_password(payload.password, user.password_hash): raise HTTPException(401, 'Email or password is incorrect.')
    return {'access_token': make_token(user.id), 'token_type':'bearer', 'user': public_state(user)}
@app.get('/me')
def me(user: User = Depends(current_user)): return public_state(user)
@app.patch('/preferences')
def update_preferences(payload: PrefsIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    allowed = {'Funny','Deep talks','Music','Food spots','Spontaneous','Gaming','Art & culture','Outdoors'}
    if any(v not in allowed for v in payload.vibes): raise HTTPException(422, 'One or more vibe selections are not supported.')
    user.intent = payload.intent; user.vibes_json = json.dumps(payload.vibes); user.radius_km = payload.radius_km
    db.commit(); return public_state(user)
@app.post('/location')
def set_location(payload: LocationIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    if not payload.consent:
        user.location_consent = False; user.latitude = None; user.longitude = None; user.available = False
        db.commit(); return {'location_enabled':False,'message':'Location removed from your account.'}
    user.latitude = payload.latitude; user.longitude = payload.longitude; user.location_consent = True
    db.commit()
    # Coordinates are stored privately for matching and are never returned by the API.
    return {'location_enabled':True,'message':'Location saved for nearby matching. Exact coordinates are not shown to other users.'}
@app.post('/match')
def find_match(db: Session = Depends(get_db), user: User = Depends(current_user)):
    if not user.location_consent or user.latitude is None or user.longitude is None: raise HTTPException(400, 'Enable location sharing before finding nearby matches.')
    if user.active_match_id:
        existing = db.get(Match, user.active_match_id)
        if existing and existing.status == 'active': return {'status':'matched','match_id':existing.id,'alias':'Your anonymous match'}
        user.active_match_id = None
    user.available = True; user.last_seen = datetime.now(timezone.utc); db.commit(); db.refresh(user)
    candidates = db.query(User).filter(User.id != user.id, User.available.is_(True), User.location_consent.is_(True), User.active_match_id.is_(None)).all()
    blocked_ids = {row.blocked_id for row in db.query(UserBlock).filter(UserBlock.blocker_id == user.id).all()}
    blocked_by_ids = {row.blocker_id for row in db.query(UserBlock).filter(UserBlock.blocked_id == user.id).all()}
    for candidate in candidates:
        if candidate.id in blocked_ids or candidate.id in blocked_by_ids:
            continue
        if match_compatible(user, candidate, db):
            # Refresh before pairing to reduce duplicate matches in the MVP. Production needs row locks/queue semantics.
            db.refresh(candidate)
            if not candidate.available or candidate.active_match_id is not None: continue
            room = Match(user_a=user.id, user_b=candidate.id, status='active')
            db.add(room); db.flush()
            user.active_match_id = room.id; candidate.active_match_id = room.id
            user.available = False; candidate.available = False
            db.commit()
            return {'status':'matched','match_id':room.id,'alias':'Your anonymous match'}
    return {'status':'waiting','message':'You are in the queue. We will keep checking for a compatible nearby person.'}
@app.get('/match/status')
def match_status(db: Session = Depends(get_db), user: User = Depends(current_user)):
    if user.active_match_id:
        room = db.get(Match, user.active_match_id)
        if room and room.status == 'active': return {'status':'matched','match_id':room.id,'alias':'Your anonymous match'}
        user.active_match_id = None; db.commit()
    return {'status':'waiting' if user.available else 'idle'}
@app.post('/match/cancel')
def cancel_match(db: Session = Depends(get_db), user: User = Depends(current_user)):
    user.available = False
    if user.active_match_id:
        room = db.get(Match, user.active_match_id)
        if room and room.status == 'active': room.status = 'ended'
        partners = db.query(User).filter(User.active_match_id == user.active_match_id, User.id != user.id).all()
        for partner in partners: partner.active_match_id = None; partner.available = False
        user.active_match_id = None
    db.commit(); return {'status':'idle'}
@app.post('/auth/logout')
def logout(db: Session = Depends(get_db), user: User = Depends(current_user)):
    user.available = False; user.location_consent = False; user.latitude = None; user.longitude = None
    if user.active_match_id:
        room = db.get(Match, user.active_match_id)
        if room and room.status == 'active': room.status = 'ended'
        partners = db.query(User).filter(User.active_match_id == user.active_match_id, User.id != user.id).all()
        for partner in partners: partner.active_match_id = None; partner.available = False
        user.active_match_id = None
    db.commit(); return {'status':'logged_out'}


class ReportIn(BaseModel):
    reason: str = Field(pattern='^(harassment|hate_or_threats|sexual_content|spam_or_scam|underage_concern|other)$')
    details: Optional[str] = Field(default=None, max_length=500)

@app.post('/safety/report')
def report_current_match(payload: ReportIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    if not user.active_match_id:
        raise HTTPException(400, 'There is no active match to report.')
    room = db.get(Match, user.active_match_id)
    if not room or room.status != 'active' or user.id not in (room.user_a, room.user_b):
        raise HTTPException(400, 'This match is no longer available.')
    reported_id = room.user_b if room.user_a == user.id else room.user_a
    report = UserReport(reporter_id=user.id, reported_id=reported_id, match_id=room.id, reason=payload.reason, details=(payload.details.strip() if payload.details else None))
    db.add(report)
    db.commit()
    return {'status': 'reported', 'message': 'Report received. Thank you for helping keep Vibe safer.'}

@app.post('/safety/block')
def block_current_match(db: Session = Depends(get_db), user: User = Depends(current_user)):
    if not user.active_match_id:
        raise HTTPException(400, 'There is no active match to block.')
    room = db.get(Match, user.active_match_id)
    if not room or room.status != 'active' or user.id not in (room.user_a, room.user_b):
        raise HTTPException(400, 'This match is no longer available.')
    blocked_id = room.user_b if room.user_a == user.id else room.user_a
    existing = db.query(UserBlock).filter(UserBlock.blocker_id == user.id, UserBlock.blocked_id == blocked_id).first()
    if not existing:
        db.add(UserBlock(blocker_id=user.id, blocked_id=blocked_id))
    room.status = 'ended'
    user.active_match_id = None
    user.available = False
    partner = db.get(User, blocked_id)
    if partner:
        partner.active_match_id = None
        partner.available = False
    db.commit()
    return {'status': 'blocked', 'message': 'User blocked. They will not be matched with you again.'}

@app.websocket('/ws/chat')
async def chat_socket(websocket: WebSocket, token: str, match_id: int):
    # WebSocket browser clients cannot set Authorization headers, so this local MVP
    # passes the short-lived bearer token as a query parameter. Use WSS and a safer
    # ticket-exchange flow before any public deployment.
    await websocket.accept()
    db = SessionLocal()
    user_id = None
    try:
        user_id = read_token(token)
        user = db.get(User, user_id)
        room = db.get(Match, match_id)
        if not user or not room or room.status != 'active' or user_id not in (room.user_a, room.user_b) or user.active_match_id != match_id:
            await websocket.send_json({'type': 'error', 'message': 'This chat is no longer available.'})
            await websocket.close(code=4403)
            return

        # Load only this room's recent messages; sender IDs never leave the backend.
        history = db.query(ChatMessage).filter(ChatMessage.match_id == match_id).order_by(ChatMessage.id.desc()).limit(100).all()
        history.reverse()
        await websocket.send_json({'type': 'history', 'messages': [
            {'content': item.content, 'created_at': item.created_at.isoformat(), 'sender_label': 'You' if item.sender_id == user_id else 'Stranger'}
            for item in history
        ]})
        chat_connections.setdefault(match_id, {})[websocket] = user_id

        while True:
            payload = await websocket.receive_json()
            if not isinstance(payload, dict) or payload.get('type') != 'message':
                continue
            content = payload.get('content', '')
            if not isinstance(content, str):
                continue
            content = content.strip()
            if not content:
                continue
            if len(content) > 500:
                await websocket.send_json({'type': 'error', 'message': 'Messages must be 500 characters or fewer.'})
                continue

            # Recheck the room on every send so ended chats cannot keep messaging.
            db.refresh(room)
            db.refresh(user)
            if room.status != 'active' or user.active_match_id != match_id:
                await websocket.send_json({'type': 'ended', 'message': 'This chat has ended.'})
                await websocket.close(code=4001)
                break

            message = ChatMessage(match_id=match_id, sender_id=user_id, content=content)
            db.add(message); db.commit(); db.refresh(message)
            recipients = list(chat_connections.get(match_id, {}).items())
            stale = []
            for connection, recipient_id in recipients:
                try:
                    await connection.send_json({
                        'type': 'message',
                        'content': message.content,
                        'created_at': message.created_at.isoformat(),
                        'sender_label': 'You' if recipient_id == user_id else 'Stranger'
                    })
                except Exception:
                    stale.append(connection)
            for connection in stale:
                chat_connections.get(match_id, {}).pop(connection, None)
    except WebSocketDisconnect:
        pass
    except HTTPException:
        try: await websocket.send_json({'type': 'error', 'message': 'Your session expired. Sign in again.'})
        except Exception: pass
        try: await websocket.close(code=4401)
        except Exception: pass
    except Exception:
        try: await websocket.send_json({'type': 'error', 'message': 'Chat connection error. Please reconnect.'})
        except Exception: pass
    finally:
        if user_id is not None:
            connections = chat_connections.get(match_id, {})
            connections.pop(websocket, None)
            if not connections:
                chat_connections.pop(match_id, None)
        db.close()
