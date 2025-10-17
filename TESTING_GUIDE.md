# Quick Testing Guide

## Prerequisites
Ensure you have the following environment variables configured:
```
TWILIO_ACCOUNT_SID=your_account_sid
TWILIO_AUTH_TOKEN=your_auth_token
TWILIO_PHONE_NUMBER=your_twilio_phone
TWILIO_WHATSAPP_FROM_NUMBER=whatsapp:+14155238886
STRIPE_SECRET_KEY=your_stripe_key
STRIPE_PRICE_ID_ESSENTIAL=price_xxx
STRIPE_PRICE_ID_ELITE=price_xxx
EMAIL_FROM=your_email@domain.com
EMAIL_PASSWORD=your_email_password
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
```

## Starting the Application

1. **Install dependencies:**
   ```powershell
   pip install -r requirements.txt
   ```

2. **Run the server:**
   ```powershell
   python web.py
   ```

3. **Open browser:**
   ```
   http://localhost:8000
   ```

## Testing Checklist

### Theme Toggle
- [ ] Click theme toggle on landing page
- [ ] Verify theme persists when navigating to login
- [ ] Verify theme persists when navigating to register
- [ ] Verify theme persists when navigating to subscribe
- [ ] Verify theme persists after browser refresh
- [ ] Test on mobile (responsive behavior)

### WhatsApp Option
- [ ] Go to Subscribe page
- [ ] Select "Essential" plan
- [ ] Verify three radio options: SMS, WhatsApp, Email
- [ ] Select "WhatsApp" option
- [ ] Enter phone number in international format (+1234567890)
- [ ] Click "Subscribe Now"
- [ ] Verify Stripe checkout accepts whatsapp channel
- [ ] Complete test payment
- [ ] Verify subscription created with whatsapp channel

### UI/UX Improvements
- [ ] Landing page animations work (scroll to see fade-in)
- [ ] Metric cards have floating animation
- [ ] Plan cards on subscribe page animate on scroll
- [ ] Card hover effects work (lift effect)
- [ ] Buttons have smooth hover states
- [ ] Forms have focus states on inputs
- [ ] All text is readable in both themes

### Functionality (Regression Testing)
- [ ] Register new account works
- [ ] Login with existing account works
- [ ] Dashboard shows user's active subscriptions
- [ ] Free plan subscription works
- [ ] Essential plan (SMS) subscription works
- [ ] Essential plan (Email) subscription works
- [ ] **NEW:** Essential plan (WhatsApp) subscription works
- [ ] Elite plan subscription works
- [ ] Alerts are sent correctly for each channel
- [ ] Scraper runs and finds new listings
- [ ] Database operations work correctly

## Common Issues & Solutions

### Issue: Theme doesn't persist
**Solution:** Check browser localStorage is enabled and not in private mode

### Issue: WhatsApp not sending
**Solution:** 
- Verify TWILIO_WHATSAPP_FROM_NUMBER is set
- Check Twilio WhatsApp sandbox is activated
- Verify phone number is in international format (+1234567890)
- Check recipient has opted into WhatsApp sandbox

### Issue: Stripe checkout fails with whatsapp
**Solution:** Check web.py line ~200, ensure "whatsapp" is in allowed channels list

### Issue: Animations not working
**Solution:** 
- Check browser supports Intersection Observer API
- Verify JavaScript is enabled
- Check console for errors (F12)

### Issue: CSS not loading
**Solution:**
- Hard refresh browser (Ctrl+Shift+R)
- Check network tab for CSS file load
- Verify template files were saved correctly

## Manual Testing Flow

### Test 1: New User Journey with WhatsApp
1. Clear browser cookies/localStorage
2. Visit http://localhost:8000
3. Click theme toggle to switch to dark mode
4. Click "Get Started" button
5. Click "Create Account" on login page
6. Register with email and password
7. Verify redirect to subscribe page
8. Verify theme is still dark
9. Select Essential plan
10. Choose "WhatsApp" radio button
11. Enter phone: +15551234567 (test number)
12. Click "Subscribe Now"
13. Complete Stripe test checkout
14. Verify redirect to dashboard
15. Check database: subscription should have channel="whatsapp"

### Test 2: Theme Persistence
1. Start with light theme on landing page
2. Click theme toggle (should go dark)
3. Navigate to /subscribe
4. Verify page loads in dark theme
5. Refresh page (F5)
6. Verify theme is still dark
7. Open new tab to http://localhost:8000
8. Verify new tab loads in dark theme
9. Click toggle to light theme
10. Close and reopen browser
11. Visit site again
12. Verify light theme is remembered

### Test 3: Mobile Responsiveness
1. Open Chrome DevTools (F12)
2. Toggle device toolbar (Ctrl+Shift+M)
3. Select iPhone 12 Pro
4. Test theme toggle button is accessible
5. Test navigation menu works
6. Test forms are usable (inputs not too small)
7. Test plan cards stack vertically
8. Test buttons are tappable (min 44x44px)
9. Test text is readable without zoom
10. Select iPad Pro
11. Verify layout adapts to tablet size

## Database Verification

After testing, check the database:

```powershell
# Connect to SQLite database
sqlite3 craiseek.db

# Check subscriptions with WhatsApp
SELECT * FROM subscribers WHERE channel = 'whatsapp';

# Verify user accounts created
SELECT * FROM users;

# Check sessions table
SELECT * FROM sessions;

# Exit SQLite
.quit
```

## Performance Testing

1. Open Chrome DevTools -> Lighthouse tab
2. Run performance audit
3. Target scores:
   - Performance: >90
   - Accessibility: >95
   - Best Practices: >90
   - SEO: >90

## Security Checklist

- [ ] Passwords are hashed (not stored in plaintext)
- [ ] Session tokens are secure
- [ ] API keys are in environment variables (not hardcoded)
- [ ] CSRF protection is enabled (if implemented)
- [ ] SQL injection prevention (parameterized queries)
- [ ] XSS prevention (template escaping)

## Next Steps After Testing

1. **If all tests pass:**
   - Deploy to production server
   - Monitor error logs
   - Set up alerts for failed payments
   - Configure real Twilio WhatsApp number

2. **If tests fail:**
   - Note which tests failed
   - Check error messages in console
   - Review IMPROVEMENTS.md for implementation details
   - Check relevant code files
   - Report issues for debugging

## Support

If you encounter issues:
1. Check console errors (F12 -> Console)
2. Check network requests (F12 -> Network)
3. Review server logs in terminal
4. Verify environment variables are set
5. Check database for data integrity

---

**Remember:** The WhatsApp feature requires:
- Active Twilio account with WhatsApp enabled
- Phone numbers must opt-in to WhatsApp sandbox (development)
- Or use verified WhatsApp Business profile (production)
