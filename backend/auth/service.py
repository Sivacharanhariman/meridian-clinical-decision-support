"""Demo HMAC authentication and fresh resource/action authorization.

The token contains only a stable subject and lifetime. Neither assignments nor
delegations are token claims. All sensitive writes check live authority inside
the same short transaction that changes the session.
"""
import base64
import hashlib
import hmac
import json
import threading
import time
from datetime import datetime, timezone

from backend.domain.contracts import Actor, DemoLoginResponse, SessionPermissions
from backend.errors import ApiFailure


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


class AuthService:
    def __init__(self, repository, actors: list[dict], settings):
        self.repository = repository
        self.actors = {a["actorId"]: Actor.model_validate(a) for a in actors}
        self.secret = settings.auth_secret.encode()
        self.lifetime = settings.token_lifetime_seconds
        self.authority_lock = threading.RLock()
        self.available = True
        # INSERT OR IGNORE preserves a revocation across application restarts.
        with repository.connect() as conn:
            conn.execute("INSERT OR IGNORE INTO delegations VALUES ('nurse-delegated', 1)")

    def login(self, actor_id: str) -> DemoLoginResponse:
        actor = self.actors.get(actor_id)
        if actor is None:
            raise ApiFailure(401, "INVALID_DEMO_IDENTITY", "Choose an available synthetic demo identity.")
        now = int(time.time())
        payload = _encode(json.dumps({"sub": actor_id, "iat": now, "exp": now + self.lifetime}, separators=(",", ":")).encode())
        signature = _encode(hmac.new(self.secret, payload.encode(), hashlib.sha256).digest())
        return DemoLoginResponse(accessToken=f"{payload}.{signature}", tokenType="bearer", actor=actor,
                                 expiresAt=datetime.fromtimestamp(now + self.lifetime, timezone.utc))

    def authenticate(self, token: str) -> Actor:
        try:
            payload, signature = token.split(".")
            expected = hmac.new(self.secret, payload.encode(), hashlib.sha256).digest()
            if not hmac.compare_digest(_decode(signature), expected):
                raise ValueError("signature")
            claims = json.loads(_decode(payload))
            if set(claims) != {"sub", "iat", "exp"} or type(claims["exp"]) is not int or type(claims["iat"]) is not int:
                raise ValueError("claims")
            if claims["exp"] <= time.time() or claims["iat"] > time.time() + 30:
                raise ValueError("expired")
            actor = self.actors.get(claims["sub"])
            if actor is None:
                raise ValueError("subject")
            return actor
        except (ValueError, TypeError, KeyError, UnicodeError, json.JSONDecodeError):
            raise ApiFailure(401, "INVALID_TOKEN", "The demo session token is invalid or expired.") from None

    def authorize(self, actor: Actor, resource: dict | None, action: str, *, conn=None) -> dict:
        if resource is None or resource["tenant_id"] != actor.tenantId:
            raise ApiFailure(404, "SESSION_INACCESSIBLE", "Session not found or inaccessible.")
        if conn is None:
            with self.authority_lock, self.repository.connect() as connection:
                return self.authorize(actor, resource, action, conn=connection)
        assignment = conn.execute("SELECT active FROM assignments WHERE actor_id=? AND session_id=?", (actor.actorId, resource["session_id"])).fetchone()
        if not assignment or not assignment[0]:
            raise ApiFailure(404, "SESSION_INACCESSIBLE", "Session not found or inaccessible.")
        if action == "CLINICIAN_OVERRIDE":
            if not self.available:
                raise ApiFailure(403, "AUTHORIZATION_UNAVAILABLE", "Current override authority cannot be verified. Escalation and documentation remain available.")
            if actor.role == "CLINICIAN":
                return {"source": "authoritative-clinician-role-and-current-assignment", "rule": "CLINICIAN_OVERRIDE_FRESH"}
            delegation = conn.execute("SELECT active FROM delegations WHERE actor_id=?", (actor.actorId,)).fetchone()
            if not delegation or not delegation[0]:
                raise ApiFailure(403, "OVERRIDE_NOT_AUTHORIZED", "An active clinician privilege or delegation is required for an override.")
            return {"source": "authoritative-live-delegation-and-current-assignment", "rule": "DELEGATED_OVERRIDE_FRESH"}
        if action not in {"VIEW_SESSION", "TRIAGE", "ACCEPT_RECOMMENDATION", "DOCUMENT_PATIENT_REFUSAL", "ESCALATE_TO_CLINICIAN", "VIEW_AUDIT", "RENDER_METRIC"}:
            raise ApiFailure(403, "ACTION_NOT_AUTHORIZED", "This action is not authorized.")
        return {"source": "authoritative-tenant-and-session-assignment", "rule": "TENANT_AND_ASSIGNMENT"}

    def permissions(self, actor: Actor, resource: dict, *, conn=None) -> SessionPermissions:
        self.authorize(actor, resource, "VIEW_SESSION", conn=conn)
        try:
            self.authorize(actor, resource, "CLINICIAN_OVERRIDE", conn=conn)
            override = True
        except ApiFailure:
            override = False
        return SessionPermissions(canView=True, canAccept=True, canDocumentRefusal=True,
                                  canEscalate=True, canOverride=override,
                                  authorizationServiceAvailable=self.available)

    def set_available(self, available: bool):
        with self.authority_lock:
            self.available = available

    def revoke_delegation(self, actor_id: str):
        self._set_delegation(actor_id, False)

    def grant_delegation(self, actor_id: str):
        self._set_delegation(actor_id, True)

    def _set_delegation(self, actor_id: str, active: bool):
        with self.authority_lock, self.repository.connect() as conn:
            conn.execute("INSERT INTO delegations VALUES (?,?) ON CONFLICT(actor_id) DO UPDATE SET active=excluded.active", (actor_id, int(active)))

    def revoke_assignment(self, actor_id: str, session_id: str):
        self._set_assignment(actor_id, session_id, False)

    def grant_assignment(self, actor_id: str, session_id: str):
        self._set_assignment(actor_id, session_id, True)

    def _set_assignment(self, actor_id: str, session_id: str, active: bool):
        with self.authority_lock, self.repository.connect() as conn:
            conn.execute("INSERT INTO assignments VALUES (?,?,?) ON CONFLICT(actor_id,session_id) DO UPDATE SET active=excluded.active", (actor_id, session_id, int(active)))
