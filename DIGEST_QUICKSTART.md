# Weekly Digest System - Quick Start Guide

## Overview
The weekly digest system automatically sends curated listing emails to FREE tier users every week, encouraging upgrades and referrals.

## Setup (5 Minutes)

### 1. Set Environment Variables
```bash
# Required for digest emails
EMAIL_SMTP_HOST=smtp.gmail.com
EMAIL_SMTP_PORT=587
EMAIL_SMTP_USERNAME=your-email@gmail.com
EMAIL_SMTP_PASSWORD=your-app-specific-password
EMAIL_FROM_ADDRESS=noreply@marketseek.com

# Required for admin endpoint
ADMIN_API_KEY=create_a_strong_random_key_here
```

**Generating a strong admin key:**
```bash
# Python
python -c "import secrets; print(secrets.token_urlsafe(32))"

# Or online
# https://www.random.org/strings/
```

### 2. Install Dependencies
```bash
pip install jinja2  # Already in requirements.txt
```

### 3. Restart Application
```bash
# Database will auto-migrate on startup
python -m uvicorn web:app --reload
```

## Manual Testing

### Send Digest to All Eligible Users
```bash
curl -X POST http://localhost:8000/admin/send-digests \
  -H "X-Admin-Key: your_admin_key_here"
```

**Response:**
```json
{
  "status": "completed",
  "sent": 15,
  "errors": 0,
  "total_eligible": 15
}
```

### Check Eligibility
Users are eligible if:
- ✅ `tier = 'FREE'`
- ✅ `email IS NOT NULL`
- ✅ `last_digest_sent` is NULL or >7 days ago

### Query Eligible Users (SQLite)
```sql
SELECT email, last_digest_sent 
FROM subscribers
WHERE tier = 'FREE'
AND email IS NOT NULL
AND (last_digest_sent IS NULL OR last_digest_sent < datetime('now', '-7 days'));
```

## Production Automation

### Option 1: Cron Job (Linux/Mac)
```bash
# Edit crontab
crontab -e

# Add this line (runs every Sunday at 9 AM)
0 9 * * 0 curl -X POST https://marketseek.com/admin/send-digests \
  -H "X-Admin-Key: $ADMIN_API_KEY" \
  >> /var/log/marketseek-digest.log 2>&1
```

### Option 2: Windows Task Scheduler
```powershell
# Create PowerShell script: send-digest.ps1
$headers = @{
    "X-Admin-Key" = $env:ADMIN_API_KEY
}
Invoke-RestMethod -Uri "https://marketseek.com/admin/send-digests" `
  -Method Post -Headers $headers

# Schedule in Task Scheduler:
# - Trigger: Weekly, Sunday, 9:00 AM
# - Action: powershell.exe -File "C:\path\to\send-digest.ps1"
```

### Option 3: Cloud Scheduler (Google Cloud, AWS)
**Google Cloud:**
```bash
gcloud scheduler jobs create http weekly-digest \
  --schedule="0 9 * * 0" \
  --uri="https://marketseek.com/admin/send-digests" \
  --http-method=POST \
  --headers="X-Admin-Key=your_key"
```

**AWS EventBridge + Lambda:**
```python
import requests

def lambda_handler(event, context):
    response = requests.post(
        "https://marketseek.com/admin/send-digests",
        headers={"X-Admin-Key": os.environ["ADMIN_API_KEY"]}
    )
    return response.json()
```

## Email Content

### What Users Receive
1. **Header**: "🏠 Your Weekly Digest"
2. **Listings Section**: Up to 10 best matches from past 7 days
3. **Upgrade CTA**: "Want Instant Alerts?" box
4. **Referral Section**: Prominently displays referral code with social sharing
5. **Footer**: Marketseek branding + social proof

### Customization
Edit `templates/digest_email.html`:
- Change listing count: Modify `limit=10` in endpoint
- Change styling: Update `<style>` section
- Change CTA copy: Edit "Want Instant Alerts?" box
- Change social proof: Update "Join 10,000+ renters"

## Monitoring

### Check Logs
```bash
# Application logs
tail -f app.log | grep "Digest"

# Look for:
# - "Digest sent to user@example.com"
# - "Failed to send digest to user@example.com: ..."
```

### Check Database
```sql
-- Recently sent digests
SELECT email, last_digest_sent 
FROM subscribers
WHERE last_digest_sent IS NOT NULL
ORDER BY last_digest_sent DESC
LIMIT 20;

-- Users never received digest
SELECT email, created_at
FROM subscribers
WHERE tier = 'FREE'
AND email IS NOT NULL
AND last_digest_sent IS NULL;
```

## Troubleshooting

### Issue: No Emails Sent
**Check:**
1. SMTP credentials correct?
   ```python
   from alerts import EmailService
   from config import get_settings
   
   service = EmailService(get_settings())
   # Try manual send
   ```

2. Users eligible?
   ```sql
   SELECT COUNT(*) FROM subscribers 
   WHERE tier = 'FREE' AND email IS NOT NULL;
   ```

3. Admin key correct?
   ```bash
   curl -X POST http://localhost:8000/admin/send-digests \
     -H "X-Admin-Key: wrong_key"
   # Should return 403 Forbidden
   ```

### Issue: Emails Going to Spam
**Solutions:**
- Add SPF record for your domain
- Set up DKIM signing
- Use reputable SMTP provider (SendGrid, Mailgun, AWS SES)
- Avoid spam trigger words in subject/body

### Issue: Slow Sending
If you have >1000 users:
- Add rate limiting to endpoint
- Batch sends (100 at a time)
- Use background task queue (Celery, RQ)

**Example with batching:**
```python
# In web.py
BATCH_SIZE = 100
for i in range(0, len(free_users), BATCH_SIZE):
    batch = free_users[i:i+BATCH_SIZE]
    for user in batch:
        # send digest
        time.sleep(0.1)  # Rate limit
```

## Best Practices

### Timing
- **Best day**: Sunday morning (rental searches peak Sunday/Monday)
- **Best time**: 8-10 AM local time
- **Avoid**: Friday/Saturday nights

### Content
- ✅ Keep it concise (top 10 listings max)
- ✅ Make CTAs prominent
- ✅ Highlight referral rewards
- ✅ Test subject lines (A/B testing)

### Frequency
- Current: Weekly (every 7 days)
- Too frequent: Daily/every other day (spam)
- Too infrequent: Monthly (low engagement)

## Analytics (TODO)

Track these metrics:
```python
# Email opens (requires tracking pixel)
# Click-through rate on listings
# Upgrade conversion rate
# Referral code shares from digest
```

**Implementation idea:**
```python
# Add to digest_email.html
<img src="{{ base_url }}/track/open/{{ user_id }}" width="1" height="1" />

# Add endpoint
@app.get("/track/open/{user_id}")
async def track_email_open(user_id: int):
    # Log open event
    return Response(content=b"", media_type="image/png")
```

## Support

### Common Questions

**Q: Can users opt out of digests?**
A: Yes, they can upgrade to Essential/Elite tier or adjust preferences in `/settings` (TODO: add preference toggle)

**Q: What if no listings match user's criteria?**
A: Email still sends with "No new listings this week" message and upgrade CTA

**Q: How do I test the digest template?**
A:
```python
# In Python shell
from alerts import EmailService
from config import get_settings
from db import Listing

service = EmailService(get_settings())
test_listings = [
    Listing(id=1, title="Test", url="http://test.com", price=1000, ...)
]
service.send_digest_email(
    "your-test@email.com",
    "TESTCODE123",
    test_listings,
    "http://localhost:8000"
)
```

**Q: Can I customize per user?**
A: Yes! The digest already filters listings by user's search criteria. You can add more personalization in `get_listings_from_past_week()`

---

## Quick Commands Reference

```bash
# Send digest manually
curl -X POST http://localhost:8000/admin/send-digests \
  -H "X-Admin-Key: $ADMIN_API_KEY"

# Check eligible users count
sqlite3 marketseek.db "SELECT COUNT(*) FROM subscribers WHERE tier='FREE' AND email IS NOT NULL"

# View recent digest sends
sqlite3 marketseek.db "SELECT email, last_digest_sent FROM subscribers ORDER BY last_digest_sent DESC LIMIT 10"

# Reset digest timestamp (for testing)
sqlite3 marketseek.db "UPDATE subscribers SET last_digest_sent = NULL WHERE email='test@example.com'"
```

---

**Need Help?**
- Check logs in `app.log`
- Review `MARKETSEEK_MARKETING_IMPLEMENTATION.md`
- Check email service configuration in `config.py`
- Test SMTP connection manually

**Last Updated:** December 2024
