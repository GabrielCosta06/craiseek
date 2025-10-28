# Environment Variables Setup for Monetization Features

## Required Stripe Configuration

Add these to your `.env` file:

```bash
# Stripe API Configuration
STRIPE_API_KEY=sk_test_...  # Use sk_live_... for production
STRIPE_WEBHOOK_SECRET=whsec_...

# Stripe Price IDs (create these in Stripe Dashboard)
STRIPE_PRICE_ID_ESSENTIAL=price_...  # $3.90/month with 3-day trial
STRIPE_PRICE_ID_ELITE=price_...      # $6.90/month
STRIPE_PRICE_ID_LIFETIME=price_...   # $149 one-time payment
```

## How to Create Stripe Products

### 1. Essential Plan ($3.90/month)
1. Go to Stripe Dashboard → Products → Create Product
2. Name: "Marketseek Essential"
3. Pricing: $3.90 USD, Recurring monthly
4. Go to Pricing tab → Add free trial: 3 days
5. Copy the Price ID (starts with `price_`)
6. Add to `.env` as `STRIPE_PRICE_ID_ESSENTIAL`

### 2. Elite Plan ($6.90/month)
1. Create Product → "Marketseek Elite"
2. Pricing: $6.90 USD, Recurring monthly
3. Copy Price ID
4. Add to `.env` as `STRIPE_PRICE_ID_ELITE`

### 3. Lifetime Plan ($149 one-time)
1. Create Product → "Marketseek Lifetime"
2. Pricing: $149 USD, **One-time payment** (not recurring)
3. Copy Price ID
4. Add to `.env` as `STRIPE_PRICE_ID_LIFETIME`

### 4. Webhook Setup
1. Stripe Dashboard → Developers → Webhooks → Add endpoint
2. Endpoint URL: `https://yourdomain.com/stripe/webhook`
3. Events to listen for: `checkout.session.completed`
4. Copy Webhook Signing Secret (starts with `whsec_`)
5. Add to `.env` as `STRIPE_WEBHOOK_SECRET`

## Testing Mode

For development, use Stripe test keys:
- API Key: starts with `sk_test_`
- Price IDs: starts with `price_test_`
- Webhook Secret: starts with `whsec_test_`

Use test cards:
- Success: `4242 4242 4242 4242`
- Requires authentication: `4000 0025 0000 3155`
- Declined: `4000 0000 0000 9995`

## Verification Checklist

Run these checks before going live:

- [ ] All three Stripe Price IDs are set
- [ ] Webhook endpoint is accessible from internet
- [ ] Webhook is configured in Stripe dashboard
- [ ] Test checkout flow for all three plans
- [ ] Verify trial period works for Essential
- [ ] Test lifetime purchase creates correct database record
- [ ] Confirm referral code generation works
- [ ] Test referral reward processing

## Database Migration

The lifetime fields are automatically added when you run the app:
```bash
python -c "from db import init_db; init_db()"
```

This will add:
- `is_lifetime` column (INTEGER)
- `lifetime_purchased_at` column (TIMESTAMP)

## Quick Start Commands

```bash
# Install dependencies
pip install stripe fastapi uvicorn

# Set environment variables
cp .env.example .env
# Edit .env with your Stripe keys

# Initialize database
python -c "from db import init_db; init_db()"

# Run the server
uvicorn web:app --reload

# Test the new pages
# http://localhost:8000/for-resellers
# http://localhost:8000/subscribe
# http://localhost:8000/referrals
```

## Monitoring

After launch, monitor these in Stripe Dashboard:
- MRR (Monthly Recurring Revenue)
- Trial conversion rate
- Churn rate
- Lifetime purchase count

Set up notifications for:
- Failed payments
- Subscription cancellations
- High-value lifetime purchases ($149)

## Support

For issues:
1. Check Stripe Dashboard logs
2. Review webhook event history
3. Check application logs for errors
4. Verify environment variables are loaded

## Security Notes

- Never commit `.env` file to git
- Use `sk_live_` keys only in production
- Enable Stripe fraud detection
- Set up 2FA on Stripe account
- Regularly review webhook endpoint logs
