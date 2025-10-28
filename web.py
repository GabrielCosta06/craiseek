"""FastAPI web application for Marketseek rental alert service."""
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
    set_referral_code,
    get_subscriber_by_referral_code,
    record_referral,
    grant_referral_reward,
    get_all_referrals,
    get_pending_referrals,
    get_free_users_for_digest,
    update_digest_sent,
    get_listings_from_past_week,
    increment_successful_referrals,
    mark_subscriber_as_lifetime,
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
            "Track up to 3 favorite locations",
        ],
        "action": "Start for free",
    },
    {
        "id": "essential",
        "name": "Essential",
        "price": "$3.90",
        "badge": "🎁 3-Day Free Trial",
        "frequency": "/month",
        "tagline": "Pick SMS, WhatsApp or email — instant alerts, zero delays.",
        "features": [
            "🎉 3-day free trial, cancel anytime",
            "Instant alerts via your choice of SMS, WhatsApp or email",
            "Unlimited location tracking",
            "Direct link payloads so you can respond faster",
            "Priority support in under 6 hours",
        ],
        "action": "Start Free Trial",
        "trial_days": 3,
        "trial_info": "No credit card charge for 3 days. Cancel anytime during trial at no cost.",
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
            "Five-minute crawl loop with VIP queueing",
            "Instant location heatmaps & comps",
            "Concierge support with human escalation",
        ],
        "action": "Unlock Elite",
    },
    {
        "id": "lifetime",
        "name": "Lifetime",
        "price": "$149",
        "badge": "🔥 Limited Offer",
        "frequency": "one-time",
        "tagline": "Pay once, use forever. Lock in Elite features for life.",
        "features": [
            "✨ All Elite features included forever",
            "No recurring payments ever",
            "Priority customer support for life",
            "Early access to new features",
            "Locked-in price (never increases)",
            "🎁 Perfect for early adopters & power users",
        ],
        "action": "Claim Lifetime Access",
        "limited": True,
        "limited_spots": 50,
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
    referral_code = form.get("referral_code", "").strip()

    plan_config: Dict[str, Dict[str, object]] = {
        "essential": {
            "price_id": settings.stripe_price_id_essential,
            "channels": [channel_choice if channel_choice in {"sms", "email", "whatsapp"} else "sms"],
            "mode": "subscription",
        },
        "elite": {
            "price_id": settings.stripe_price_id_elite,
            "channels": ["sms", "email", "whatsapp"],
            "mode": "subscription",
        },
        "lifetime": {
            "price_id": settings.stripe_price_id_lifetime,
            "channels": ["sms", "email", "whatsapp"],
            "mode": "payment",
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
    mode = config["mode"]  # type: ignore[assignment]

    success_url = str(request.url_for("landing")) + "?success=true"
    cancel_url = str(request.url_for("landing")) + "?canceled=true"

    # Add 3-day free trial for Essential plan only (not for lifetime)
    trial_config = {}
    if plan == "essential":
        trial_config = {"subscription_data": {"trial_period_days": 3}}
    
    try:
        session = stripe.checkout.Session.create(
            mode=mode,
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=success_url,
            cancel_url=cancel_url,
            phone_number_collection={"enabled": bool({"sms", "whatsapp"}.intersection(channels))},
            customer_creation="always",
            metadata={
                "tier": plan.upper(),
                "channels": channels_str,
                "requested_channel": channel_choice,
                "referral_code": referral_code if referral_code else "",
                "is_lifetime": "true" if plan == "lifetime" else "false",
            },
            **trial_config,
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
        referral_code = metadata.get("referral_code", "").strip()
        is_lifetime = metadata.get("is_lifetime", "false").lower() == "true"
        
        whatsapp_contact = None
        if "whatsapp" in channels and phone:
            whatsapp_contact = phone if phone.startswith("whatsapp:") else f"whatsapp:{phone}"

        if not phone and not email:
            logger.warning("Checkout session missing contact info", extra={"session_id": session.get("id")})
        else:
            inserted = upsert_subscriber(
                tier=tier,
                channels=channels,
                phone=phone if "sms" in channels or "whatsapp" in channels else None,
                email=email if "email" in channels else None,
                whatsapp=whatsapp_contact,
            )
            
            # Mark as lifetime if applicable
            if is_lifetime and email:
                mark_subscriber_as_lifetime(email)
                logger.info("Marked subscriber as lifetime", extra={"email": email})
            
            # Generate referral code for new subscriber
            if email and inserted:
                set_referral_code(email)
            
            # Process referral if code was provided
            if referral_code and email:
                referrer = get_subscriber_by_referral_code(referral_code)
                if referrer:
                    # Record the referral
                    record_referral(referral_code, email, phone)
                    # Find pending referrals for this referee
                    pending = get_pending_referrals(referral_code)
                    for ref in pending:
                        if ref.referee_email == email:
                            # Grant reward (1 month free) to referrer
                            grant_referral_reward(ref.id)
                            logger.info("Referral reward processed", extra={
                                "referrer_code": referral_code,
                                "referee": email
                            })
            
            logger.info(
                "Processed subscriber from Stripe",
                extra={
                    "phone": phone,
                    "email": email,
                    "channels": channels,
                    "tier": tier,
                    "is_lifetime": is_lifetime,
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


@app.get("/referrals", response_class=HTMLResponse)
async def referrals_page(request: Request) -> HTMLResponse:
    """Show referral dashboard with code and tracking."""
    user = _current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    
    # Get or create subscriber record for this user
    subscription = get_subscriber_by_email(user.email)
    
    # Generate referral code if they don't have one
    if subscription and not subscription.referral_code:
        set_referral_code(user.email)
        subscription = get_subscriber_by_email(user.email)
    
    # Get referral stats
    referrals = []
    rewarded_count = 0
    pending_count = 0
    
    if subscription and subscription.referral_code:
        referrals = get_all_referrals(subscription.referral_code)
        rewarded_count = sum(1 for r in referrals if r.reward_granted)
        pending_count = sum(1 for r in referrals if not r.reward_granted)
    
    context = {
        "request": request,
        "user": user,
        "subscription": subscription,
        "referrals": referrals,
        "rewarded_count": rewarded_count,
        "pending_count": pending_count,
        "base_url": str(request.base_url).rstrip("/"),
    }
    return templates.TemplateResponse("referrals.html", context)


@app.get("/promo", response_class=HTMLResponse)
async def promo_page(request: Request) -> HTMLResponse:
    """Show promotional page for free trial and referral program."""
    return templates.TemplateResponse("promo.html", {"request": request, "user": _current_user(request)})


@app.get("/for-resellers", response_class=HTMLResponse)
async def resellers_promo_page(request: Request) -> HTMLResponse:
    """Show promotional page specifically targeting resellers and flippers."""
    return templates.TemplateResponse("promo_resellers.html", {"request": request, "user": _current_user(request)})


@app.post("/admin/send-digests")
async def send_weekly_digests(request: Request) -> JSONResponse:
    """Send weekly digest emails to all eligible free users. Admin endpoint."""
    from alerts import EmailService
    
    # Simple admin protection (you should implement proper auth)
    admin_key = request.headers.get("X-Admin-Key")
    if admin_key != settings.admin_api_key:
        raise HTTPException(status_code=403, detail="Unauthorized")
    
    email_service = EmailService(settings)
    free_users = get_free_users_for_digest()
    sent_count = 0
    error_count = 0
    
    base_url = str(request.base_url).rstrip("/")
    
    for user in free_users:
        try:
            # Get listings from past week matching user's criteria
            # Extract keywords from user's search (this is simplified - you may need to store keywords)
            listings = get_listings_from_past_week(
                keywords="",  # You'd need to store user's search keywords
                max_price=None,
                min_bedrooms=None,
                limit=10
            )
            
            # Send digest
            email_service.send_digest_email(
                to_email=user.email,
                referral_code=user.referral_code or "",
                listings=listings,
                base_url=base_url
            )
            
            # Mark as sent
            update_digest_sent(user.id)
            sent_count += 1
            logger.info(f"Digest sent to {user.email}")
            
        except Exception as exc:
            error_count += 1
            logger.error(f"Failed to send digest to {user.email}: {exc}")
    
    return JSONResponse({
        "status": "completed",
        "sent": sent_count,
        "errors": error_count,
        "total_eligible": len(free_users)
    })

