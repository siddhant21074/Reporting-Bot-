"""Dashboard page routes.

Role enforcement lives in the dependencies (``require_admin`` /
``require_full_access``) and in the ``wa_id_scope`` passed to every repository
call, so a USER-role account is filtered inside the SQL query rather than in the
template.
"""

import logging
import os
from datetime import datetime
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import FileResponse, RedirectResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import (
    COOKIE_NAME,
    CurrentUser,
    can_access_contact,
    cookie_params,
    get_current_user,
    issue_session,
    require_admin,
    require_full_access,
)
from app.core.config import settings
from app.db.base import get_db
from app.db.models import ReportStatus, UserRole
from app.repositories import history, settings_store, users as users_repo
from app.web.templating import flash_from_query, render, system_health

logger = logging.getLogger("app.web.routes")
router = APIRouter()

PAGE_SIZE = 25


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------


@router.get("/login")
async def login_page(
    request: Request,
    next: str = Query(default="/"),
    db: AsyncSession = Depends(get_db),
):
    """Shows the sign-in form."""
    from app.web.templating import templates

    accounts = await users_repo.list_users(db)

    return templates.TemplateResponse(
        "login.html",
        {
            "request": request,
            "app_name": settings.app.name,
            "environment": settings.app.environment.title(),
            "year": datetime.now().year,
            "next_url": next,
            "error": request.query_params.get("err"),
            "notice": request.query_params.get("msg"),
            "username": "",
            "setup_hint": not accounts,
        },
    )


@router.post("/login")
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    next: str = Form(default="/"),
    db: AsyncSession = Depends(get_db),
):
    """Verifies credentials and issues the session cookie."""
    user = await users_repo.authenticate(db, username, password)

    if user is None:
        return RedirectResponse(
            f"/login?err={quote('That username and password did not match.')}"
            f"&next={quote(next, safe='')}",
            status_code=303,
        )

    if user.role_enum is UserRole.USER and not user.wa_id:
        return RedirectResponse(
            f"/login?err={quote('Your account is not linked to a WhatsApp number yet.')}",
            status_code=303,
        )

    # Only redirect to a path on this site.
    target = next if next.startswith("/") and not next.startswith("//") else "/"
    response = RedirectResponse(target, status_code=303)
    response.set_cookie(
        COOKIE_NAME,
        issue_session(user.id),
        max_age=settings.admin.session_max_age,
        **cookie_params(),
    )
    return response


@router.post("/logout")
async def logout() -> Response:
    """Clears the session cookie."""
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(COOKIE_NAME, path="/")
    return response


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


@router.get("/")
async def dashboard(
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Overview: volume, delivery health, live conversations and system status."""
    scope = user.scope

    stats = await history.dashboard_stats(db, wa_id_scope=scope)
    activity = await history.reports_per_day(db, days=7, wa_id_scope=scope)
    recent = await history.recent_activity(db, limit=8, wa_id_scope=scope)

    store = request.app.state.session_store
    live = await store.active_sessions()
    live_sessions = [
        {"sender_id": s.sender_id, "state": s.state.value}
        for s in live
        if s.state.value != "IDLE" and (scope is None or s.sender_id == scope)
    ]

    return render(
        request,
        "dashboard.html",
        user=user,
        page_title="Dashboard",
        page_sub=f"Activity over the last {settings.app.retention_days} days",
        active="dashboard",
        flash=flash_from_query(request),
        stats=stats,
        activity=activity,
        # A flat zero row would divide by zero; 1 keeps the bars at the baseline.
        chart_peak=max([day["total"] for day in activity] + [1]),
        recent=recent,
        live_sessions=live_sessions,
        health=system_health(),
        last_purge=getattr(request.app.state, "last_purge_at", None),
    )


# ---------------------------------------------------------------------------
# Contacts
# ---------------------------------------------------------------------------


@router.get("/contacts")
async def contacts_page(
    request: Request,
    q: Optional[str] = Query(default=None),
    offset: int = Query(default=0, ge=0),
    user: CurrentUser = Depends(require_full_access),
    db: AsyncSession = Depends(get_db),
):
    """Lists everyone who has messaged the bot. Not available to USER accounts."""
    contacts, total = await history.list_contacts(db, search=q, limit=PAGE_SIZE, offset=offset)

    store = request.app.state.session_store
    live_states = {
        s.sender_id: s.state.value for s in await store.active_sessions() if s.state.value != "IDLE"
    }

    return render(
        request,
        "contacts.html",
        user=user,
        page_title="Contacts",
        page_sub="Everyone who has messaged the bot",
        active="contacts",
        flash=flash_from_query(request),
        contacts=contacts,
        total=total,
        search=q,
        offset=offset,
        page_size=PAGE_SIZE,
        live_states=live_states,
    )


@router.get("/contacts/{wa_id}")
async def contact_detail(
    request: Request,
    wa_id: str,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """One contact: full transcript plus every report they generated."""
    from app.auth import NotAuthorised

    if not can_access_contact(user, wa_id):
        raise NotAuthorised("You can only view your own messages and reports.")

    contact = await history.get_contact(db, wa_id)
    if contact is None:
        from app.core.exceptions import NotFoundError

        raise NotFoundError(f"No contact with the number {wa_id}.")

    messages = await history.list_messages(db, wa_id, limit=500)
    reports, _ = await history.list_reports(db, wa_id=wa_id, limit=100)

    store = request.app.state.session_store
    live = next((s for s in await store.active_sessions() if s.sender_id == wa_id), None)

    linked_login = await users_repo.get_user_for_wa_id(db, wa_id)

    return render(
        request,
        "contact_detail.html",
        user=user,
        page_title=contact.display,
        page_sub=contact.wa_id if contact.display_name else "WhatsApp contact",
        active="contacts",
        flash=flash_from_query(request),
        contact=contact,
        messages=messages,
        reports=reports,
        live_state=live.state.value if live and live.state.value != "IDLE" else None,
        linked_login=linked_login,
        retention_days=settings.app.retention_days,
    )


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------


@router.get("/reports")
async def reports_page(
    request: Request,
    q: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    offset: int = Query(default=0, ge=0),
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Every report the signed-in account may see."""
    status_filter = None
    if status:
        try:
            status_filter = ReportStatus(status)
        except ValueError:
            status_filter = None

    reports, total = await history.list_reports(
        db,
        status=status_filter,
        search=q,
        limit=PAGE_SIZE,
        offset=offset,
        wa_id_scope=user.scope,
    )

    return render(
        request,
        "reports.html",
        user=user,
        page_title="My reports" if user.is_restricted else "Reports",
        page_sub="Generated documents, newest first",
        active="reports",
        flash=flash_from_query(request),
        reports=reports,
        total=total,
        search=q,
        status_filter=status,
        status_options=[(s.value, s.label) for s in ReportStatus],
        offset=offset,
        page_size=PAGE_SIZE,
        retention_days=settings.app.retention_days,
    )


@router.get("/reports/{report_id}/download")
async def download_report(
    report_id: int,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Streams a generated document.

    The scope check happens here, not in the template that rendered the link --
    guessing a report id must not reveal another contact's document.
    """
    from app.auth import NotAuthorised
    from app.core.exceptions import NotFoundError

    report = await history.get_report(db, report_id)
    if report is None:
        raise NotFoundError("That report no longer exists.")

    if not can_access_contact(user, report.wa_id):
        logger.warning(
            f"'{user.username}' tried to download report {report_id} belonging to {report.wa_id}.",
            extra={"event": "download_denied", "username": user.username},
        )
        raise NotAuthorised("You can only download your own reports.")

    if not report.file_path or not os.path.exists(report.file_path):
        raise NotFoundError("The file for that report has been deleted by the retention policy.")

    media_type = (
        "application/pdf"
        if report.file_path.lower().endswith(".pdf")
        else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    return FileResponse(
        report.file_path,
        media_type=media_type,
        filename=os.path.basename(report.file_path),
    )


# ---------------------------------------------------------------------------
# Settings (administrators only)
# ---------------------------------------------------------------------------


@router.get("/settings")
async def settings_page(
    request: Request,
    user: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Channel credentials, AI provider and model, retention."""
    from app.ai.registry import CHAT, STT, fallback_models, providers_for_role
    from app.repositories.settings_store import EDITABLE_KEYS, MASKED_VALUE

    saved = await settings_store.saved_keys(db)
    values = {key: settings._str(key) for key in EDITABLE_KEYS}

    chat_providers = providers_for_role(CHAT)
    stt_providers = providers_for_role(STT)

    # Model suggestions for the datalists, keyed by provider for the JS.
    model_catalogue = {p["id"]: fallback_models(p["id"], CHAT) for p in chat_providers}
    model_catalogue.update({p["id"]: fallback_models(p["id"], STT) for p in stt_providers})

    base_url = settings.app.base_url or "https://your-domain"

    return render(
        request,
        "settings.html",
        user=user,
        page_title="Settings",
        page_sub="Channels, models and retention. Changes apply immediately.",
        active="settings",
        flash=flash_from_query(request),
        values=values,
        saved=saved,
        masked=MASKED_VALUE,
        chat_providers=chat_providers,
        stt_providers=stt_providers,
        model_catalogue=model_catalogue,
        health=system_health(),
        webhooks={
            "whatsapp": f"{base_url}/webhook/whatsapp",
            "telegram": f"{base_url}/webhook/telegram",
        },
        telegram_ready=False,
        audit=await users_repo.recent_audit(db, limit=10),
    )


@router.post("/settings")
async def settings_save(
    request: Request,
    user: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Persists the settings form and applies it to the running process."""
    from app.repositories.settings_store import EDITABLE_KEYS

    form = await request.form()
    submitted = {key: str(form.get(key, "")) for key in EDITABLE_KEYS}

    # Unchecked checkboxes are simply absent from the form body.
    for toggle in ("WHATSAPP_ENABLED", "TELEGRAM_ENABLED"):
        submitted[toggle] = "true" if form.get(toggle) else "false"

    try:
        changed = await settings_store.save_settings(db, submitted, actor=user.username)
    except Exception as exc:
        logger.error(f"Saving settings failed: {exc}", exc_info=True)
        return RedirectResponse(f"/settings?err={quote('Could not save those settings.')}", status_code=303)

    if changed:
        await users_repo.record_audit(
            db,
            actor=user.username,
            action="Updated settings",
            detail=", ".join(sorted(changed)),
        )
        # The provider objects read settings lazily, but a cached client would
        # keep using the old key.
        request.app.state.ai_provider = _rebuild_ai_provider()
        message = f"Saved {len(changed)} setting{'' if len(changed) == 1 else 's'}."
    else:
        message = "No changes to save."

    return RedirectResponse(f"/settings?ok={quote(message)}", status_code=303)


@router.get("/settings/models")
async def refresh_models(
    request: Request,
    role: str = Query(default="chat"),
    provider: str = Query(default="openai"),
    user: CurrentUser = Depends(require_admin),
):
    """Fetches a provider's live model list and reports what it found.

    Kept as a redirect-with-message rather than JSON so it works without any
    client-side framework.
    """
    from app.ai.registry import CHAT, STT, list_models

    role_key = STT if role == "stt" else CHAT
    config = settings.stt if role == "stt" else settings.llm
    api_key = config.api_key if config.provider == provider else ""

    models = await list_models(
        provider,
        api_key=api_key,
        role=role_key,
        http_client=getattr(request.app.state, "http_client", None),
    )
    free = sum(1 for model in models if model["free"])

    message = f"{provider}: {len(models)} models available"
    if free:
        message += f", {free} free"
    return RedirectResponse(f"/settings?ok={quote(message)}", status_code=303)


def _rebuild_ai_provider():
    """Recreates the AI provider so new credentials take effect at once."""
    from app.ai import AIProvider

    return AIProvider()


# ---------------------------------------------------------------------------
# Logins (administrators only)
# ---------------------------------------------------------------------------


@router.get("/settings/users")
async def users_page(
    request: Request,
    wa_id: Optional[str] = Query(default=None),
    user: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Lists dashboard logins and the form to create one."""
    contacts, _ = await history.list_contacts(db, limit=200)

    return render(
        request,
        "users.html",
        user=user,
        page_title="Logins",
        page_sub="Who can sign in, and what they can see",
        active="users",
        flash=flash_from_query(request),
        users=await users_repo.list_users(db),
        contacts=contacts,
        prefill_wa_id=wa_id,
    )


@router.post("/settings/users")
async def users_create(
    username: str = Form(...),
    password: str = Form(...),
    role: str = Form(...),
    display_name: str = Form(default=""),
    wa_id: str = Form(default=""),
    admin: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Creates a login."""
    try:
        role_enum = UserRole(role)
    except ValueError:
        return RedirectResponse(f"/settings/users?err={quote('Unknown role.')}", status_code=303)

    try:
        created = await users_repo.create_user(
            db,
            username=username,
            password=password,
            role=role_enum,
            display_name=display_name,
            wa_id=wa_id,
            created_by=admin.username,
        )
    except ValueError as exc:
        return RedirectResponse(f"/settings/users?err={quote(str(exc))}", status_code=303)

    await users_repo.record_audit(
        db,
        actor=admin.username,
        action="Created login",
        target=created.username,
        detail=f"role={role_enum.value}" + (f", number={created.wa_id}" if created.wa_id else ""),
    )
    return RedirectResponse(
        f"/settings/users?ok={quote(f'Created the {role_enum.label.lower()} login {created.username}.')}",
        status_code=303,
    )


@router.post("/settings/users/{user_id}/toggle")
async def users_toggle(
    user_id: int,
    admin: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Enables or disables a login."""
    account = await users_repo.get_user(db, user_id)
    if account is None:
        return RedirectResponse(f"/settings/users?err={quote('That login no longer exists.')}", status_code=303)

    try:
        await users_repo.update_user(db, account, is_active=not account.is_active)
    except ValueError as exc:
        return RedirectResponse(f"/settings/users?err={quote(str(exc))}", status_code=303)

    action = "Enabled" if account.is_active else "Disabled"
    await users_repo.record_audit(db, actor=admin.username, action=f"{action} login", target=account.username)
    return RedirectResponse(
        f"/settings/users?ok={quote(f'{action} {account.username}.')}", status_code=303
    )


@router.post("/settings/users/{user_id}/delete")
async def users_delete(
    user_id: int,
    admin: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Deletes a login."""
    account = await users_repo.get_user(db, user_id)
    if account is None:
        return RedirectResponse(f"/settings/users?err={quote('That login no longer exists.')}", status_code=303)

    username = account.username
    try:
        await users_repo.delete_user(db, account)
    except ValueError as exc:
        return RedirectResponse(f"/settings/users?err={quote(str(exc))}", status_code=303)

    await users_repo.record_audit(db, actor=admin.username, action="Deleted login", target=username)
    return RedirectResponse(f"/settings/users?ok={quote(f'Deleted {username}.')}", status_code=303)
