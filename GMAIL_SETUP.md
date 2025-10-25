# 📧 Gmail Setup Guide for Price Tracker

This guide will help you configure Gmail to send email alerts from your Price Tracker application.

## 🔧 Step-by-Step Setup

### Step 1: Enable 2-Factor Authentication

1. **Go to Google Account Settings**
   - Visit [https://myaccount.google.com/](https://myaccount.google.com/)
   - Sign in with your Gmail account

2. **Navigate to Security**
   - Click on "Security" in the left sidebar
   - Look for "2-Step Verification"

3. **Enable 2-Step Verification**
   - Click "Get started" if not already enabled
   - Follow the setup process (phone number, backup codes, etc.)
   - **Important**: This is required to generate app passwords

### Step 2: Generate App Password

1. **Go to App Passwords**
   - In Google Account Settings, go to "Security"
   - Under "2-Step Verification", click "App passwords"
   - You might need to sign in again

2. **Create New App Password**
   - Select "Mail" from the dropdown
   - Select "Other (Custom name)" for device
   - Enter "Price Tracker" as the name
   - Click "Generate"

3. **Copy the Password**
   - Google will show a 16-character password like: `abcd efgh ijkl mnop`
   - **Copy this password immediately** - you won't see it again!
   - Remove spaces: `abcdefghijklmnop`

### Step 3: Configure Your .env File

1. **Create .env File**
   - In your `price_tracker` directory, create a file named `.env`
   - Add the following content:

```env
# Email Configuration
EMAIL_ADDRESS=your_email@gmail.com
EMAIL_APP_PASSWORD=abcdefghijklmnop
ADMIN_EMAIL=your_email@gmail.com

# Email Settings
QUIET_HOURS_START=22:00
QUIET_HOURS_END=08:00
DIGEST_FREQUENCY=daily
MAX_EMAILS_PER_HOUR=10

# Database
DATABASE_PATH=./data/products.db
LOG_LEVEL=INFO
```

2. **Replace the Values**
   - Replace `your_email@gmail.com` with your actual Gmail address
   - Replace `abcdefghijklmnop` with your actual 16-character app password

### Step 4: Test Your Configuration

1. **Run the Application**
   ```bash
   streamlit run app.py
   ```

2. **Go to Email Management**
   - Click on "Email Management" in the sidebar
   - Go to the "Gmail Setup" tab
   - Click "🧪 Test Email Configuration"

3. **Check Your Email**
   - If successful, you'll receive a test email
   - If it fails, check your .env file configuration

## 🚨 Troubleshooting

### Common Issues

**❌ "Authentication failed"**
- Double-check your app password (no spaces)
- Ensure 2-factor authentication is enabled
- Try generating a new app password

**❌ "Invalid credentials"**
- Verify your email address in .env file
- Check that the app password is correct
- Make sure you're using the app password, not your regular password

**❌ "Connection refused"**
- Check your internet connection
- Ensure Gmail SMTP is not blocked by firewall
- Try using a different network

**❌ "Quota exceeded"**
- Gmail has daily sending limits
- Wait 24 hours or use a different Gmail account
- Consider upgrading to Google Workspace for higher limits

### Gmail Sending Limits

- **Free Gmail**: 500 emails per day
- **Google Workspace**: 2,000 emails per day
- **Rate Limit**: ~100 emails per hour

## 📧 Email Features

### Supported Email Types

1. **Price Alerts**
   - Individual product price changes
   - Bulk alerts for multiple products
   - Rich HTML emails with charts

2. **Digest Emails**
   - Daily/weekly summaries
   - Best deals and price drops
   - Product recommendations

3. **Scheduled Alerts**
   - Custom frequency (1-168 hours)
   - Quiet hours support
   - Multiple recipients

### Email Templates

- **Individual Alert**: Single product with price chart
- **Bulk Alert**: Multiple products in one email
- **Digest**: Summary with statistics and trends

## 🔒 Security Best Practices

1. **Never commit .env file to version control**
2. **Use app passwords, not your main password**
3. **Regularly rotate app passwords**
4. **Monitor email sending activity**
5. **Use environment variables in production**

## 📱 Mobile Setup

### Gmail App
- Use the same app password
- Enable notifications for Price Tracker emails
- Set up filters to organize alerts

### Other Email Clients
- IMAP settings: `imap.gmail.com:993`
- SMTP settings: `smtp.gmail.com:587`
- Use your app password for authentication

## 🆘 Need Help?

If you're still having issues:

1. **Check the logs** in your application
2. **Verify .env file** format and values
3. **Test with a simple email** first
4. **Contact support** with error messages

## 📊 Monitoring

### Track Email Performance
- Check "Email Stats" tab in Email Management
- Monitor delivery rates
- Set up email analytics

### Best Practices
- Don't send too many emails (respect Gmail limits)
- Use quiet hours to avoid spam complaints
- Provide clear unsubscribe options
- Monitor bounce rates

---

**🎉 You're all set!** Your Price Tracker can now send beautiful email alerts to keep you updated on price changes.
