# Marketseek - Facebook Marketplace Rental Alerts

Production-ready application that monitors Facebook Marketplace for rental listings, stores new listings, and notifies subscribers through their preferred channel. A lightweight FastAPI site powers tiered subscriptions, Stripe Checkout, referral rewards, and a polished dashboard experience.

## 🚀 Key Features

### Core Functionality
- 🏠 **Intelligent scraping** of Facebook Marketplace with exponential backoff and resilient HTML parsing
- 💾 **SQLite persistence** for listings, users, sessions, referrals, and subscriber preferences
- 📱 **Multi-channel alerts** (SMS, WhatsApp, email) via Twilio + SMTP
- 🎯 **Smart filtering** by keywords, price, bedrooms, and location

### Marketing & Growth
- 🎁 **Enhanced Referral Program**: Both parties get 1 month Elite tier free
- 📧 **Weekly Digest Emails**: Curated listings for FREE tier users
- 🔓 **WhatsApp Unlock Milestone**: Unlocked after 3 successful referrals
- 📊 **Social Proof**: "Join 10,000+ renters" across all touchpoints
- 🎯 **3-Day Free Trial**: Essential plan includes no-card trial

### Web Application
- ⚡ **FastAPI backend** with animated landing page and dashboard
- 💳 **Stripe integration** with webhook processing
- 🔐 **Secure authentication** with session management
- 📱 **Responsive design** optimized for mobile

### Subscription Tiers
- **FREE**: Weekly digest emails, search by keywords/price
- **ESSENTIAL**: SMS alerts, priority matching, 3-day free trial
- **ELITE**: WhatsApp alerts, unlimited filters, fastest alerts

## ⚠️ Important Notes

**Facebook Marketplace Scraping**: Facebook uses dynamic rendering and has strict anti-scraping measures. This implementation provides basic HTML parsing but for production use, consider:
- Using Facebook's Graph API (requires app approval)
- Implementing Selenium/Playwright for dynamic content
- Adding proxy rotation and rate limiting
- Respecting Facebook's robots.txt and Terms of Service

## 📋 Quick Start

### 1. Install Dependencies
```bash
# Python 3.11+ required
pip install -r requirements.txt
```

### 2. Configure Environment
Copy `.env.example` to `.env` and configure:

```bash
# Database
DATABASE_PATH=marketseek.db

# Scraping
TARGET_URL=https://www.facebook.com/marketplace/category/propertyrentals
SCRAPE_INTERVAL_SECONDS=300

# Twilio (SMS/WhatsApp)
TWILIO_ACCOUNT_SID=your_sid
TWILIO_AUTH_TOKEN=your_token
TWILIO_FROM_NUMBER=+1234567890
TWILIO_WHATSAPP_FROM_NUMBER=whatsapp:+1234567890

# Stripe (Payments)
STRIPE_API_KEY=sk_live_...
STRIPE_PRICE_ID_ESSENTIAL=price_...
STRIPE_PRICE_ID_ELITE=price_...
STRIPE_WEBHOOK_SECRET=whsec_...

# Email (SMTP)
EMAIL_SMTP_HOST=smtp.gmail.com
EMAIL_SMTP_PORT=587
EMAIL_SMTP_USERNAME=your-email@gmail.com
EMAIL_SMTP_PASSWORD=your-app-password
EMAIL_FROM_ADDRESS=noreply@marketseek.com

# Admin
ADMIN_API_KEY=your_secret_admin_key
```

### 3. Run the Application

**Start Web Server:**
```bash
uvicorn web:app --host 0.0.0.0 --port 8000 --reload
```

**Start Scraper (separate terminal):**
```bash
# Continuous monitoring
python scraper.py run

# Single pass (testing)
python scraper.py --once
```

**Send Weekly Digests:**
```bash
curl -X POST http://localhost:8000/admin/send-digests \
  -H "X-Admin-Key: your_admin_key"
```

## 📁 Project Structure

```
marketseek/
├── web.py              # FastAPI application (routes, auth, Stripe)
├── scraper.py          # Facebook Marketplace scraper
├── db.py               # Database layer (SQLite ORM)
├── alerts.py           # Multi-channel alert service
├── auth.py             # Authentication utilities
├── config.py           # Environment configuration
├── requirements.txt    # Python dependencies
├── templates/          # Jinja2 HTML templates
│   ├── index.html          # Landing page
│   ├── subscribe.html      # Pricing & plans
│   ├── dashboard.html      # User dashboard
│   ├── referrals.html      # Referral program
│   ├── digest_email.html   # Weekly digest template
│   └── ...                 # Other pages
├── tests/              # Pytest test suite
└── docs/               # Additional documentation
```

## 📚 Documentation

- **[MARKETSEEK_MARKETING_IMPLEMENTATION.md](MARKETSEEK_MARKETING_IMPLEMENTATION.md)** - Complete marketing features guide
- **[DIGEST_QUICKSTART.md](DIGEST_QUICKSTART.md)** - Weekly digest system setup
- **[FREE_TRIAL_REFERRAL_DOCS.md](FREE_TRIAL_REFERRAL_DOCS.md)** - Referral program technical docs

## 🗄️ Database Schema

### Tables
- **`listings`** - Scraped rental listings with timestamps
- **`subscribers`** - User subscriptions with tier and channel preferences
- **`referrals`** - Referral tracking and reward status
- **`users`** - Dashboard authentication
- **`sessions`** - Session tokens for auth

### Key Columns (subscribers)
```sql
tier TEXT               -- FREE, ESSENTIAL, ELITE
channel_preferences TEXT-- Comma-separated: sms,email,whatsapp
referral_code TEXT      -- Unique referral code (MS[8-char])
successful_referrals INT-- Count of paid referrals
whatsapp_unlocked INT   -- Unlocked at 3 referrals
last_digest_sent TIMESTAMP-- Weekly digest tracking
```

## 🔌 API Endpoints

### Public Routes
- `GET /` - Landing page
- `GET /subscribe` - Pricing plans
- `GET /promo` - Promotional page (free trial + referrals)
- `POST /subscribe/free` - Free tier signup
- `POST /buy` - Stripe Checkout session

### Authenticated Routes
- `GET /dashboard` - User dashboard
- `GET /referrals` - Referral program page
- `GET /settings` - Account settings
- `POST /logout` - Sign out

### Admin Routes
- `POST /admin/send-digests` - Trigger weekly digest (requires `X-Admin-Key`)

### Webhooks
- `POST /stripe/webhook` - Stripe event processing

## 🎨 Features in Detail

### 1. Referral Program
- **Reward**: Both referrer and referee get 1 month Elite tier
- **Unlock**: WhatsApp alerts after 3 successful referrals
- **Sharing**: One-click social sharing (Twitter, Facebook, WhatsApp, Email)
- **Tracking**: Real-time dashboard with referral history

### 2. Weekly Digest
- **Recipients**: FREE tier users (sent every 7 days)
- **Content**: Top 10 listings from past week
- **CTAs**: Upgrade prompt + referral sharing
- **Automation**: Cron job or cloud scheduler

### 3. Subscription Tiers
| Feature | FREE | ESSENTIAL | ELITE |
|---------|------|-----------|-------|
| Price | $0 | $9.99/mo | $24.99/mo |
| Weekly Digest | ✅ | ✅ | ✅ |
| SMS Alerts | ❌ | ✅ | ✅ |
| WhatsApp Alerts | ❌ | ❌ | ✅* |
| Free Trial | ❌ | 3 days | ❌ |
| Filters | Basic | Priority | Unlimited |

*WhatsApp can be unlocked with 3 successful referrals

## 🧪 Testing

Run the full test suite:
```bash
pytest tests/ -v
```

Test coverage:
- HTML parsing (`test_scraper.py`)
- Authentication flow (`test_auth_flow.py`)
- Stripe webhooks (`test_webhook.py`)
- Alert delivery (`test_alerts.py`)
- Subscription forms (`test_subscribe.py`)

## 🚀 Deployment

### Production Checklist
1. ✅ Set strong `ADMIN_API_KEY`
2. ✅ Configure Stripe webhook endpoint
3. ✅ Set up SMTP provider (SendGrid, Mailgun, AWS SES)
4. ✅ Enable Twilio for SMS/WhatsApp
5. ✅ Schedule weekly digest cron job
6. ✅ Set up monitoring (logs, errors, uptime)
7. ✅ Configure SSL certificate
8. ✅ Add domain to Facebook API whitelist (if using Graph API)

### Cron Jobs
```bash
# Weekly digest (Sundays at 9 AM)
0 9 * * 0 curl -X POST https://marketseek.com/admin/send-digests -H "X-Admin-Key: $KEY"

# Scraper (every 5 minutes)
*/5 * * * * cd /app && python scraper.py --once
```

## 🔒 Security

- Password hashing with PBKDF2
- Session tokens with secure random generation
- Stripe webhook signature verification
- Admin endpoint protection with API key
- SQL injection prevention via parameterized queries
- HTTPS required for production

## 📊 Monitoring

Track these metrics:
- **Scraper**: Listings found per run, errors, response times
- **Alerts**: Delivery success rate per channel
- **Digests**: Open rate, click-through rate, upgrade conversions
- **Referrals**: Successful referrals per user, WhatsApp unlock rate
- **Subscriptions**: MRR, churn rate, trial conversion rate

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Run tests (`pytest`)
4. Commit changes (`git commit -m 'Add amazing feature'`)
5. Push to branch (`git push origin feature/amazing-feature`)
6. Open a Pull Request

## 📄 License

This project is licensed under the MIT License - see LICENSE file for details.

## 🆘 Support

For issues and questions:
- Check the [documentation](./docs/)
- Review [MARKETSEEK_MARKETING_IMPLEMENTATION.md](MARKETSEEK_MARKETING_IMPLEMENTATION.md)
- Open an issue on GitHub

## 🎯 Roadmap

- [ ] Facebook Graph API integration
- [ ] Mobile app (React Native)
- [ ] AI-powered listing recommendations
- [ ] Price drop alerts
- [ ] Saved searches
- [ ] Multi-city support
- [ ] Browser extension
- [ ] Slack/Discord integration

---

**Built with ❤️ for renters everywhere**

*Never miss your perfect apartment again.*


```bash- `POST /subscribe/free` — free-tier email signups.

uvicorn web:app --host 0.0.0.0 --port 8000 --reload- `POST /buy` — Stripe Checkout Session creation for paid tiers (channels encoded in metadata).

```- `POST /stripe/webhook` — signature verification, tier + channel persistence, and subscriber upsert.

- `GET /health` — health probe (`{"status": "ok"}`).

Public endpoints:

- `GET /` — animated landing page with live metrics, testimonial, and CTA.Account + dashboard endpoints:

- `GET /subscribe` — plan comparison (Free/Essential/Elite) with channel highlights.- `GET /register` / `POST /register` — signup with PBKDF2 hashing.

- `POST /subscribe/free` — free-tier email signups.- `GET /login` / `POST /login` — email/password authentication issuing secure cookies.

- `POST /buy` — Stripe Checkout Session creation for paid tiers (channels encoded in metadata).- `POST /logout` — clears the active session.

- `POST /stripe/webhook` — signature verification, tier + channel persistence, and subscriber upsert.- `GET /dashboard` — authenticated feed of the latest listings (subscription optional).

- `GET /health` — health probe (`{"status": "ok"}`).

Configure Stripe to POST webhooks to `/stripe/webhook`.

Account + dashboard endpoints:

- `GET /register` / `POST /register` — signup with PBKDF2 hashing.## Testing

- `GET /login` / `POST /login` — email/password authentication issuing secure cookies.```bash

- `POST /logout` — clears the active session.pytest

- `GET /dashboard` — authenticated feed of the latest listings (subscription optional).```



Configure Stripe to POST webhooks to `/stripe/webhook`.## Operational Notes

- SMS/WhatsApp alerts are skipped if Twilio credentials are missing; email alerts require SMTP configuration.

## Testing- Stripe failures return HTTP 502 and log structured detail for troubleshooting.

```bash- Webhook handling is idempotent via upserts + unique indexes, preventing duplicate subscribers.

pytest- Logging uses contextual `extra={...}` payloads for observability across scraping, alerts, and web flows.
```

## Operational Notes
- SMS/WhatsApp alerts are skipped if Twilio credentials are missing; email alerts require SMTP configuration.
- Stripe failures return HTTP 502 and log structured detail for troubleshooting.
- Webhook handling is idempotent via upserts + unique indexes, preventing duplicate subscribers.
- Logging uses contextual `extra={...}` payloads for observability across scraping, alerts, and web flows.
- **Facebook Marketplace**: Consider using more robust scraping solutions (Selenium, API access) for production use.

## Legal & Compliance
This tool is designed for personal use. When using it:
- Respect Facebook's Terms of Service and robots.txt
- Implement appropriate rate limiting
- Consider using official Facebook APIs where possible
- Do not use for commercial scraping without proper authorization
