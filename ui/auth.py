"""Authentication module for CI Briefing Crew.

Users are stored in  data/users.yaml  (auto-created on first run).
The admin account from .env is always seeded into the file if missing.

Exposes:
  - render_auth()    -> (name, auth_status, username)
  - render_logout()  -> None  (call inside `with st.sidebar`)
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import re

import bcrypt
import streamlit as st
import yaml

from config.settings import settings

# ── Users file ────────────────────────────────────────────────────────────────
USERS_FILE = Path(__file__).resolve().parent.parent / "data" / "users.yaml"


def _load_users() -> dict:
    """Load users dict from YAML, seeding admin from .env if missing."""
    if USERS_FILE.exists():
        with open(USERS_FILE, "r") as f:
            data = yaml.safe_load(f) or {}
    else:
        data = {}

    users = data.get("usernames", {})

    # Always ensure the .env admin account exists
    if settings.auth_username not in users:
        users[settings.auth_username] = {
            "name":     settings.auth_name,
            "email":    settings.auth_email,
            "password": settings.auth_password_hash,
            "role":     "admin",
        }
        _save_users(users)

    return users


def _save_users(users: dict) -> None:
    USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(USERS_FILE, "w") as f:
        yaml.dump({"usernames": users}, f, default_flow_style=False)


def _hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt(12)).decode()


def _check_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except Exception:
        return False


def _is_valid_email(email: str) -> bool:
    return bool(re.match(r"^[\w.+-]+@[\w-]+\.[a-zA-Z]{2,}$", email))


# ── CSS shared by login + register ────────────────────────────────────────────
_AUTH_CSS = """
<style>
.auth-logo     { font-size: 52px; text-align: center; margin-bottom: 4px; }
.auth-title    { font-size: 26px; font-weight: 800; color: #f6ede1; text-align: center; margin-bottom: 2px; }
.auth-subtitle { font-size: 14px; color: #93826d; text-align: center; margin-bottom: 20px; }
.auth-divider  { border: none; border-top: 1px solid rgba(255,200,140,0.14); margin: 18px 0; }
</style>
"""


# ── Login ──────────────────────────────────────────────────────────────────────
def _render_login_form() -> tuple[str | None, bool | None, str | None]:
    users = _load_users()

    with st.form("login_form", clear_on_submit=False):
        st.markdown("### 🔑 Sign In")
        username = st.text_input("Username", placeholder="your username")
        password = st.text_input("Password", type="password", placeholder="••••••••")
        submitted = st.form_submit_button("Sign In", use_container_width=True, type="primary")

    if not submitted:
        return None, None, None

    username = username.strip().lower()

    if username not in users:
        st.error("❌ Username not found.")
        return None, False, None

    if not _check_password(password, users[username]["password"]):
        st.error("❌ Incorrect password.")
        return None, False, None

    # Success — write to session state (mirrors streamlit-authenticator convention)
    name = users[username].get("name", username)
    st.session_state["authentication_status"] = True
    st.session_state["username"]              = username
    st.session_state["name"]                  = name
    return name, True, username


# ── Register ───────────────────────────────────────────────────────────────────
def _render_register_form() -> None:
    users = _load_users()

    with st.form("register_form", clear_on_submit=True):
        st.markdown("### 📝 Create Account")
        full_name = st.text_input("Full name",  placeholder="Jane Doe")
        email     = st.text_input("Email",      placeholder="jane@example.com")
        username  = st.text_input("Username",   placeholder="janedoe  (no spaces)")
        password  = st.text_input("Password",   type="password", placeholder="min 6 characters")
        confirm   = st.text_input("Confirm password", type="password", placeholder="repeat password")
        submitted = st.form_submit_button("Create Account", use_container_width=True, type="primary")

    if not submitted:
        return

    # ── Validation ────────────────────────────────────────────────────────────
    errors = []
    username = username.strip().lower()
    full_name = full_name.strip()
    email = email.strip().lower()

    if not full_name:
        errors.append("Full name is required.")
    if not email or not _is_valid_email(email):
        errors.append("Enter a valid email address.")
    if not username or " " in username or len(username) < 3:
        errors.append("Username must be at least 3 characters with no spaces.")
    if username in users:
        errors.append(f"Username **{username}** is already taken.")
    if any(u["email"] == email for u in users.values()):
        errors.append("An account with that email already exists.")
    if len(password) < 6:
        errors.append("Password must be at least 6 characters.")
    if password != confirm:
        errors.append("Passwords do not match.")

    if errors:
        for e in errors:
            st.error(e)
        return

    # ── Save ──────────────────────────────────────────────────────────────────
    users[username] = {
        "name":     full_name,
        "email":    email,
        "password": _hash_password(password),
        "role":     "user",
    }
    _save_users(users)
    st.success(f"✅ Account created! Welcome, **{full_name}**. You can now sign in.")


# ── Public entry point ────────────────────────────────────────────────────────
def render_auth() -> tuple[str | None, bool | None, str | None]:
    """Render login + register tabs.

    Returns (name, auth_status, username).
    auth_status is True on successful login, False on bad credentials,
    None if no form submitted yet.
    """
    # If already logged in via session state, skip the form entirely
    if st.session_state.get("authentication_status") is True:
        return (
            st.session_state.get("name"),
            True,
            st.session_state.get("username"),
        )

    st.markdown(_AUTH_CSS, unsafe_allow_html=True)

    _, mid, _ = st.columns([1, 2, 1])
    with mid:
        st.markdown("""
        <div class="auth-logo">🧭</div>
        <div class="auth-title">CI Briefing Crew</div>
        <div class="auth-subtitle">Competitive Intelligence Platform</div>
        """, unsafe_allow_html=True)

        tab_login, tab_register = st.tabs(["🔑 Sign In", "📝 Register"])

        with tab_login:
            name, status, username = _render_login_form()
            if status is True:
                st.rerun()   # re-render app now that we're logged in

        with tab_register:
            _render_register_form()

    return None, None, None


def render_logout() -> None:
    """Logout button + user display — call inside `with st.sidebar`."""
    name = st.session_state.get("name", "User")
    st.markdown(f"👤 **{name}**")
    if st.button("🚪 Logout", use_container_width=True, key="_logout_btn"):
        for key in ("authentication_status", "username", "name"):
            st.session_state.pop(key, None)
        st.rerun()
