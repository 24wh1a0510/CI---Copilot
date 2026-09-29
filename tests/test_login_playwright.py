"""Playwright E2E tests for CI Briefing Crew login flow.

Prerequisites:
  pip install pytest-playwright playwright
  playwright install chromium

Run:
  pytest tests/test_login_playwright.py --headed          # visible browser
  pytest tests/test_login_playwright.py                   # headless (CI)

Environment:
  APP_URL   - base URL of running app  (default: http://localhost:8502)
  AUTH_USERNAME - login username       (default: admin)
  AUTH_PASSWORD - plain-text password  (default: admin123)
"""
from __future__ import annotations

import os
import time

import pytest
from playwright.sync_api import Page, expect

# ── Config ─────────────────────────────────────────────────────────────────────
APP_URL  = os.getenv("APP_URL", "http://localhost:8502")
USERNAME = os.getenv("AUTH_USERNAME", "admin")
PASSWORD = os.getenv("AUTH_PASSWORD", "admin123")


# ── Helpers ────────────────────────────────────────────────────────────────────
def _wait_for_streamlit(page: Page, timeout: int = 15_000) -> None:
    """Wait until Streamlit finishes its initial render."""
    page.wait_for_load_state("networkidle", timeout=timeout)
    # Streamlit appends this class once the React tree is mounted
    page.wait_for_selector("[data-testid='stApp']", timeout=timeout)


def _fill_login(page: Page, username: str, password: str) -> None:
    """Fill and submit the streamlit-authenticator login form."""
    # Username field — stauth renders a standard text input
    username_input = page.locator("input[type='text']").first
    username_input.fill(username)

    # Password field
    password_input = page.locator("input[type='password']").first
    password_input.fill(password)

    # Submit — stauth uses a form submit button labelled "Login"
    page.locator("button[type='submit']").click()

    # Give Streamlit a moment to re-render after form submit
    time.sleep(1)
    _wait_for_streamlit(page)


# ── Fixtures ───────────────────────────────────────────────────────────────────
@pytest.fixture()
def app_page(page: Page):
    """Navigate to the app and wait for it to load."""
    page.goto(APP_URL)
    _wait_for_streamlit(page)
    return page


# ── Tests ──────────────────────────────────────────────────────────────────────

class TestLoginPage:
    """Verify the login page renders correctly before authentication."""

    def test_login_page_renders(self, app_page: Page):
        """App shows a login form when not authenticated."""
        # The page title should be set
        expect(app_page).to_have_title("CI Briefing Crew")

    def test_login_form_has_fields(self, app_page: Page):
        """Username and password inputs are present."""
        expect(app_page.locator("input[type='text']").first).to_be_visible()
        expect(app_page.locator("input[type='password']").first).to_be_visible()

    def test_login_form_has_submit_button(self, app_page: Page):
        """A submit button is visible on the login page."""
        expect(app_page.locator("button[type='submit']").first).to_be_visible()

    def test_branding_visible(self, app_page: Page):
        """CI Briefing Crew branding text is shown on the login page."""
        expect(app_page.locator("text=CI Briefing Crew").first).to_be_visible()


class TestLoginFailure:
    """Verify wrong credentials are rejected."""

    def test_wrong_password_shows_error(self, app_page: Page):
        """Submitting wrong credentials shows an error message."""
        _fill_login(app_page, USERNAME, "wrong_password_xyz")
        # stauth renders an error via st.error which becomes a div[data-testid="stAlert"]
        error = app_page.locator("[data-testid='stAlert']").first
        expect(error).to_be_visible(timeout=8_000)

    def test_wrong_username_shows_error(self, app_page: Page):
        """Submitting unknown username shows an error message."""
        _fill_login(app_page, "nobody", "wrong")
        error = app_page.locator("[data-testid='stAlert']").first
        expect(error).to_be_visible(timeout=8_000)

    def test_dashboard_not_visible_when_not_logged_in(self, app_page: Page):
        """Dashboard page content must not appear before login."""
        # The sidebar navigation should not be visible before login
        sidebar_nav = app_page.locator("text=New Briefing")
        expect(sidebar_nav).not_to_be_visible()


class TestLoginSuccess:
    """Verify correct credentials grant access to the app."""

    def test_successful_login_shows_dashboard(self, app_page: Page):
        """Valid credentials redirect to the Dashboard page."""
        _fill_login(app_page, USERNAME, PASSWORD)
        # After login, the sidebar navigation and dashboard header appear
        expect(
            app_page.locator("text=Dashboard").first
        ).to_be_visible(timeout=10_000)

    def test_sidebar_visible_after_login(self, app_page: Page):
        """Sidebar with navigation buttons is visible after login."""
        _fill_login(app_page, USERNAME, PASSWORD)
        expect(
            app_page.locator("section[data-testid='stSidebar']")
        ).to_be_visible(timeout=10_000)

    def test_nav_buttons_present_after_login(self, app_page: Page):
        """All three navigation buttons are present after login."""
        _fill_login(app_page, USERNAME, PASSWORD)
        sidebar = app_page.locator("section[data-testid='stSidebar']")
        expect(sidebar.locator("text=Dashboard").first).to_be_visible(timeout=10_000)
        expect(sidebar.locator("text=New Briefing").first).to_be_visible()
        expect(sidebar.locator("text=History").first).to_be_visible()

    def test_logout_button_present_after_login(self, app_page: Page):
        """Logout button is visible in the sidebar after login."""
        _fill_login(app_page, USERNAME, PASSWORD)
        sidebar = app_page.locator("section[data-testid='stSidebar']")
        # stauth renders a logout button labelled "Logout"
        expect(
            sidebar.locator("button", has_text="Logout").first
        ).to_be_visible(timeout=10_000)

    def test_username_displayed_in_sidebar(self, app_page: Page):
        """The logged-in user's name appears in the sidebar."""
        _fill_login(app_page, USERNAME, PASSWORD)
        sidebar = app_page.locator("section[data-testid='stSidebar']")
        # auth.py renders "👤 **{name}**" in the sidebar
        expect(sidebar.locator("text=Administrator").first).to_be_visible(timeout=10_000)


class TestLogout:
    """Verify logout works correctly."""

    def test_logout_returns_to_login(self, app_page: Page):
        """Clicking logout brings back the login form."""
        _fill_login(app_page, USERNAME, PASSWORD)
        sidebar = app_page.locator("section[data-testid='stSidebar']")
        logout_btn = sidebar.locator("button", has_text="Logout").first
        logout_btn.wait_for(state="visible", timeout=10_000)
        logout_btn.click()
        time.sleep(1)
        _wait_for_streamlit(app_page)
        # Login form must reappear
        expect(app_page.locator("input[type='password']").first).to_be_visible(timeout=8_000)

    def test_dashboard_not_accessible_after_logout(self, app_page: Page):
        """After logout, the dashboard content is no longer visible."""
        _fill_login(app_page, USERNAME, PASSWORD)
        sidebar = app_page.locator("section[data-testid='stSidebar']")
        logout_btn = sidebar.locator("button", has_text="Logout").first
        logout_btn.wait_for(state="visible", timeout=10_000)
        logout_btn.click()
        time.sleep(1)
        _wait_for_streamlit(app_page)
        expect(app_page.locator("text=New Briefing")).not_to_be_visible()
