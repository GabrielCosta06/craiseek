from __future__ import annotations

import logging
from typing import Dict, Optional
from urllib.parse import parse_qs

import stripe
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from auth import create_session_token, hash_password, normalize_email, verify_password
from config import get_settings
from db import (
    User,
    create_session,
    delete_session,
    get_recent_listings,
    get_subscriber_count,
    get_listing_count,
    get_unique_neighborhoods,
    get_user_by_email,
    get_user_by_session,
    upsert_subscriber,
    insert_user,
)

logger = logging.getLogger(__name__)

app = FastAPI()
templates = Jinja2Templates(directory="templates")

settings = get_settings()

if settings.stripe_api_key:
    stripe.api_key = settings.stripe_api_key

SESSION_COOKIE_NAME = "session_token"
SESSION_MAX_AGE = 60 * 60 * 24 * 30  # 30 days

PLAN_DETAILS = [
    {
        "id": "free",
        "name": "Scout",
        "price": "Free",
        "badge": "Starter",
        "frequency": "",
        "tagline": "Email-only digest with dashboard access.",
        "features": [
            "Daily email digest of top 3 listings",
            "Real-time dashboard with saved search filters",
            "Track up to 3 favorite neighborhoods",
        ],
        "action": "Start for free",
    },
    {
        "id": "essential",
        "name": "Essential",
        "price": "$3.90",
        "badge": "Most Popular",
        "frequency": "/month",
        "tagline": "Pick SMS or email — instant alerts, zero delays.",
        "features": [
            "Instant alerts via your choice of SMS or email",
            "Unlimited neighborhood tracking",
            "Direct link payloads so you can respond faster",
            "Priority support in under 6 hours",
        ],
        "action": "Activate Essential",
    },
    {
        "id": "elite",
        "name": "Elite",
        "price": "$6.90",
        "badge": "Power Rental",
        "frequency": "/month",
        "tagline": "All channels unlocked: SMS, WhatsApp, and email together.",
        "features": [
            "Simultaneous SMS + WhatsApp + email alerts",
            "One-minute crawl loop with VIP queueing",
            "Instant neighborhood heatmaps & comps",
            "Concierge support with human escalation",
        ],
        "action": "Unlock Elite",
    },
]


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        max_age=SESSION_MAX_AGE,
        samesite="lax",
    )


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE_NAME)


def _current_user(request: Request) -> Optional[User]:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        return None
    return get_user_by_session(token)


def _subscription_context(
    request: Request,
    *,
    message: Optional[str] = None,
    message_type: Optional[str] = None,
    prefill: Optional[Dict[str, str]] = None,
) -> Dict[str, object]:
    return {
        "request": request,
        "user": _current_user(request),
        "plans": PLAN_DETAILS,
        "stripe_available": settings.stripe_configured,
        "message": message,
        "message_type": message_type,
        "prefill": prefill or {},
    }

@app.get("/", name="landing", response_class=HTMLResponse)
async def landing(request: Request) -> HTMLResponse:
    """Render the marketing landing page."""
    subscriber_count = get_subscriber_count()
    fomo_remaining = max(0, 20 - subscriber_count)
    listing_count = get_listing_count()
    latest_listings = get_recent_listings(limit=3)
    neighborhoods = get_unique_neighborhoods()
    context = {
        "request": request,
        "fomo_remaining": fomo_remaining,
        "subscriber_count": subscriber_count,
        "listing_count": listing_count,
        "latest_listings": latest_listings,
        "neighborhoods": neighborhoods,
        "user": _current_user(request),
    }
    return templates.TemplateResponse("index.html", context)


@app.get("/health")
async def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/subscribe", response_class=HTMLResponse)
async def subscribe_page(request: Request) -> HTMLResponse:
    status_flag = request.query_params.get("status")
    message = None
    message_type = None
    if status_flag == "free":
        message = "Free plan activated! Check your inbox for the next digest."
        message_type = "success"
    elif status_flag == "paid":
        message = "Thanks! Finish checkout to start receiving premium alerts."
        message_type = "info"
    context = _subscription_context(request, message=message, message_type=message_type)
    return templates.TemplateResponse("subscribe.html", context)


@app.post("/subscribe/free")
async def subscribe_free(request: Request) -> Response:
    form = await _parse_form_data(request)
    email = normalize_email(form.get("email", ""))
    if not email or "@" not in email:
        context = _subscription_context(
            request,
            message="Please enter a valid email address to receive digests.",
            message_type="error",
            prefill={"free_email": form.get("email", "")},
        )
        return templates.TemplateResponse("subscribe.html", context, status_code=status.HTTP_400_BAD_REQUEST)

    upsert_subscriber(tier="FREE", channels=["email"], email=email)
    response = RedirectResponse(url="/subscribe?status=free", status_code=status.HTTP_303_SEE_OTHER)
    return response


@app.post("/buy")
async def create_checkout_session(request: Request) -> JSONResponse:
    if not settings.stripe_configured:
        logger.error("Stripe credentials missing; cannot create Checkout session.")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Stripe unavailable.")

    form = await _parse_form_data(request)
    plan = (form.get("plan") or "essential").lower()
    channel_choice = (form.get("channel") or "sms").lower()

    plan_config: Dict[str, Dict[str, object]] = {
        "essential": {
            "price_id": settings.stripe_price_id_essential,
            "channels": [channel_choice if channel_choice in {"sms", "email"} else "sms"],
        },
        "elite": {
            "price_id": settings.stripe_price_id_elite,
            "channels": ["sms", "email", "whatsapp"],
        },
    }

    config = plan_config.get(plan)
    if config is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported plan selected.")

    price_id = config["price_id"]
    if not price_id:
        logger.error("Stripe price ID missing for plan", extra={"plan": plan})
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Plan unavailable.")

    channels = config["channels"]  # type: ignore[assignment]
    channels_str = ",".join(channels)

    success_url = str(request.url_for("landing")) + "?success=true"
    cancel_url = str(request.url_for("landing")) + "?canceled=true"

    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=success_url,
            cancel_url=cancel_url,
            phone_number_collection={"enabled": bool({"sms", "whatsapp"}.intersection(channels))},
            customer_creation="always",
            metadata={
                "tier": plan.upper(),
                "channels": channels_str,
                "requested_channel": channel_choice,
            },
        )
    except stripe.error.StripeError as exc:
        logger.error("Stripe error creating Checkout session", extra={"error": str(exc)})
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Stripe error.")

    return JSONResponse({"checkout_url": session.url})


@app.post("/stripe/webhook")
async def stripe_webhook(request: Request) -> JSONResponse:
    if not settings.stripe_webhook_secret:
        logger.error("Stripe webhook secret missing; cannot validate webhook.")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Stripe webhook not configured.")

    payload = await request.body()
    signature = request.headers.get("stripe-signature")
    if signature is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing Stripe signature header.")

    try:
        event = stripe.Webhook.construct_event(payload, signature, settings.stripe_webhook_secret)
    except ValueError:
        logger.error("Invalid Stripe payload.")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid payload.")
    except stripe.error.SignatureVerificationError:
        logger.error("Invalid Stripe signature.")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid signature.")

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        customer_details = session.get("customer_details") or {}
        phone = customer_details.get("phone")
        email = customer_details.get("email")
        metadata = session.get("metadata") or {}
        tier = (metadata.get("tier") or "ESSENTIAL").upper()
        channels_raw = metadata.get("channels") or "sms"
        channels = [c.strip() for c in channels_raw.split(",") if c.strip()]
        whatsapp_contact = None
        if "whatsapp" in channels and phone:
            whatsapp_contact = phone if phone.startswith("whatsapp:") else f"whatsapp:{phone}"

        if not phone:
            logger.warning("Checkout session missing phone number", extra={"session_id": session.get("id")})
        else:
            inserted = upsert_subscriber(
                tier=tier,
                channels=channels,
                phone=phone if "sms" in channels or "whatsapp" in channels else None,
                email=email if "email" in channels else None,
                whatsapp=whatsapp_contact,
            )
            logger.info(
                "Processed subscriber from Stripe",
                extra={
                    "phone": phone,
                    "email": email,
                    "channels": channels,
                    "tier": tier,
                    "inserted": inserted,
                    "session_id": session.get("id"),
                },
            )

    return JSONResponse({"status": "ok"})


@app.get("/register", response_class=HTMLResponse)
async def register_form(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("register.html", {"request": request, "user": _current_user(request)})


async def _parse_form_data(request: Request) -> Dict[str, str]:
    body = await request.body()
    data = parse_qs(body.decode("utf-8"))
    return {key: values[0] for key, values in data.items() if values}


@app.post("/register")
async def register_user(request: Request) -> Response:
    form = await _parse_form_data(request)
    normalized_email = normalize_email(form.get("email", ""))
    password = form.get("password", "").strip()

    if not normalized_email or "@" not in normalized_email:
        context = {
            "request": request,
            "error": "Please provide a valid email.",
            "user": _current_user(request),
        }
        return templates.TemplateResponse("register.html", context, status_code=status.HTTP_400_BAD_REQUEST)

    if len(password) < 8:
        context = {
            "request": request,
            "error": "Password must be at least 8 characters.",
            "user": _current_user(request),
        }
        return templates.TemplateResponse("register.html", context, status_code=status.HTTP_400_BAD_REQUEST)

    if get_user_by_email(normalized_email):
        context = {
            "request": request,
            "error": "That email is already registered. Try logging in.",
            "user": _current_user(request),
        }
        return templates.TemplateResponse("register.html", context, status_code=status.HTTP_400_BAD_REQUEST)

    password_hash = hash_password(password)
    inserted = insert_user(normalized_email, password_hash)
    if not inserted:
        context = {
            "request": request,
            "error": "Unable to create account. Please try again.",
            "user": _current_user(request),
        }
        return templates.TemplateResponse("register.html", context, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)

    user = get_user_by_email(normalized_email)
    if user is None:
        context = {
            "request": request,
            "error": "Account created but could not log in automatically.",
            "user": _current_user(request),
        }
        return templates.TemplateResponse("login.html", context, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)

    token = create_session_token()
    create_session(user.id, token)
    response = RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    _set_session_cookie(response, token)
    return response


@app.get("/login", response_class=HTMLResponse)
async def login_form(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("login.html", {"request": request, "user": _current_user(request)})


@app.post("/login")
async def login_user(request: Request) -> Response:
    form = await _parse_form_data(request)
    normalized_email = normalize_email(form.get("email", ""))
    password = form.get("password", "").strip()
    user = get_user_by_email(normalized_email)

    if user is None or not verify_password(password, user.password_hash):
        context = {
            "request": request,
            "error": "Invalid email or password.",
            "user": _current_user(request),
        }
        return templates.TemplateResponse("login.html", context, status_code=status.HTTP_400_BAD_REQUEST)

    token = create_session_token()
    create_session(user.id, token)
    response = RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    _set_session_cookie(response, token)
    return response


@app.post("/logout")
async def logout_user(request: Request) -> Response:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token:
        delete_session(token)
    response = RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    _clear_session_cookie(response)
    return response


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request) -> HTMLResponse:
    user = _current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    listings = get_recent_listings()
    context = {
        "request": request,
        "user": user,
        "listings": listings,
    }
    return templates.TemplateResponse("dashboard.html", context)
