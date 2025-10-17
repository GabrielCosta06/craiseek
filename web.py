"""FastAPI web application for Craiseek rental alert service."""
from __future__ import annotations

import logging
import secrets
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
    get_filtered_listings,
    get_all_neighborhoods,
    get_subscriber_count,
    get_listing_count,
    get_unique_neighborhoods,
    get_user_by_email,
    get_user_by_session,
    upsert_subscriber,
    insert_user,
    set_verification_token,
    verify_email,
    get_subscriber_by_email,
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
        "tagline": "Pick SMS, WhatsApp or email — instant alerts, zero delays.",
        "features": [
            "Instant alerts via your choice of SMS, WhatsApp or email",
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
    # Check for success/cancel from Stripe
    if request.query_params.get("success") == "true":
        return RedirectResponse(url="/success", status_code=status.HTTP_303_SEE_OTHER)
    
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
        message = "Email verified! You'll receive your next digest soon."
        message_type = "success"
    elif status_flag == "free_pending":
        message = "Check your email to verify your subscription and start receiving alerts."
        message_type = "info"
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

    # Generate verification token
    verification_token = secrets.token_urlsafe(32)
    
    # Create or update subscriber
    upsert_subscriber(tier="FREE", channels=["email"], email=email)
    set_verification_token(email, verification_token)
    
    # In production, send verification email here
    # For now, we'll log the verification link
    verification_url = f"{request.base_url}verify-email?token={verification_token}"
    logger.info(f"Email verification URL (send this in email): {verification_url}")
    
    # TODO: Send actual email when email service is configured
    # Example: send_verification_email(email, verification_url)
    
    response = RedirectResponse(url="/subscribe?status=free_pending", status_code=status.HTTP_303_SEE_OTHER)
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
            "channels": [channel_choice if channel_choice in {"sms", "email", "whatsapp"} else "sms"],
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

    # Get filter parameters
    min_price = request.query_params.get("min_price")
    max_price = request.query_params.get("max_price")
    neighborhood = request.query_params.get("neighborhood")
    keyword = request.query_params.get("keyword")
    
    # Convert price strings to integers
    min_price_int = None
    max_price_int = None
    if min_price and min_price.strip():
        try:
            min_price_int = int(min_price)
        except ValueError:
            pass
    if max_price and max_price.strip():
        try:
            max_price_int = int(max_price)
        except ValueError:
            pass
    
    # Get filtered or all listings
    if any([min_price_int, max_price_int, neighborhood, keyword]):
        listings = get_filtered_listings(
            min_price=min_price_int,
            max_price=max_price_int,
            neighborhood=neighborhood if neighborhood else None,
            keyword=keyword if keyword else None,
            limit=50
        )
    else:
        listings = get_recent_listings(limit=50)
    
    # Get all neighborhoods for filter dropdown
    all_neighborhoods = get_all_neighborhoods()
    
    context = {
        "request": request,
        "user": user,
        "listings": listings,
        "all_neighborhoods": all_neighborhoods,
        "filters": {
            "min_price": min_price or "",
            "max_price": max_price or "",
            "neighborhood": neighborhood or "",
            "keyword": keyword or "",
        }
    }
    return templates.TemplateResponse("dashboard.html", context)


@app.get("/privacy", response_class=HTMLResponse)
async def privacy_policy(request: Request) -> HTMLResponse:
    """Render the privacy policy page."""
    return templates.TemplateResponse("privacy.html", {"request": request, "user": _current_user(request)})


@app.get("/terms", response_class=HTMLResponse)
async def terms_of_service(request: Request) -> HTMLResponse:
    """Render the terms of service page."""
    return templates.TemplateResponse("terms.html", {"request": request, "user": _current_user(request)})


@app.get("/verify-email", response_class=HTMLResponse)
async def verify_email_endpoint(request: Request) -> Response:
    """Verify a user's email address using the verification token."""
    token = request.query_params.get("token")
    
    if not token:
        context = _subscription_context(
            request,
            message="Invalid verification link. Please check your email.",
            message_type="error",
        )
        return templates.TemplateResponse("subscribe.html", context, status_code=status.HTTP_400_BAD_REQUEST)
    
    verified = verify_email(token)
    
    if verified:
        return RedirectResponse(url="/subscribe?status=free", status_code=status.HTTP_303_SEE_OTHER)
    else:
        context = _subscription_context(
            request,
            message="Verification link expired or already used. Please subscribe again.",
            message_type="error",
        )
        return templates.TemplateResponse("subscribe.html", context, status_code=status.HTTP_400_BAD_REQUEST)


@app.get("/success", response_class=HTMLResponse)
async def success_page(request: Request) -> HTMLResponse:
    """Show success page after successful Stripe checkout."""
    return templates.TemplateResponse("success.html", {"request": request, "user": _current_user(request)})


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request) -> HTMLResponse:
    """Show account settings page."""
    user = _current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    
    # Try to find subscription by user email
    subscription = get_subscriber_by_email(user.email)
    
    context = {
        "request": request,
        "user": user,
        "subscription": subscription,
        "message": request.query_params.get("message"),
        "message_type": request.query_params.get("message_type", "info"),
    }
    return templates.TemplateResponse("settings.html", context)


@app.get("/faq", response_class=HTMLResponse)
async def faq_page(request: Request) -> HTMLResponse:
    """Render the FAQ page."""
    return templates.TemplateResponse("faq.html", {"request": request, "user": _current_user(request)})
