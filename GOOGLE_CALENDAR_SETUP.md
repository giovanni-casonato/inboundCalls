# Google Calendar Integration Setup Guide

## Overview
This guide will help you set up Google Calendar integration for your AI phone assistant so callers can schedule appointments.

## Prerequisites
- A Google Cloud Platform account
- A Google Calendar that you want to use for appointments

## Setup Steps

### 1. Create a Google Cloud Project

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Click "Create Project" or select an existing project
3. Give your project a name (e.g., "Wholesale Atlas Phone Bot")

### 2. Enable Google Calendar API

1. In your Google Cloud Project, go to **APIs & Services** > **Library**
2. Search for "Google Calendar API"
3. Click on it and press **Enable**

### 3. Create Service Account Credentials

1. Go to **APIs & Services** > **Credentials**
2. Click **Create Credentials** > **Service Account**
3. Fill in the details:
   - Service account name: `calendar-bot`
   - Service account ID: `calendar-bot` (auto-generated)
   - Click **Create and Continue**
4. Grant access (optional, can skip this step)
5. Click **Done**

### 4. Generate Service Account Key

1. Click on the service account you just created
2. Go to the **Keys** tab
3. Click **Add Key** > **Create new key**
4. Choose **JSON** format
5. Click **Create** - this will download a JSON file to your computer

### 5. Share Your Calendar with the Service Account

1. Open the JSON file you downloaded and find the `client_email` field (looks like `calendar-bot@project-id.iam.gserviceaccount.com`)
2. Copy this email address
3. Open [Google Calendar](https://calendar.google.com)
4. Find the calendar you want to use (or create a new one)
5. Click the three dots next to it > **Settings and sharing**
6. Scroll to **Share with specific people**
7. Click **Add people**
8. Paste the service account email
9. Set permission to **Make changes to events**
10. Click **Send**

### 6. Configure Environment Variables

You have two options:

#### Option A: Environment Variable (Recommended for Production)

Set the entire JSON credentials as an environment variable:

```bash
export GOOGLE_CALENDAR_CREDENTIALS_JSON='{"type":"service_account","project_id":"...","private_key":"...","client_email":"..."}'
```

#### Option B: File Path (Good for Local Development)

Place the JSON file in your project directory and set:

```bash
export GOOGLE_CALENDAR_CREDENTIALS_FILE='path/to/your/credentials.json'
```

### 7. Set Calendar ID (Optional)

If you want to use a specific calendar (not your primary one):

1. Go to Google Calendar
2. Click the three dots next to the calendar > **Settings and sharing**
3. Scroll down to **Integrate calendar**
4. Copy the **Calendar ID** (looks like `abc123@group.calendar.google.com`)
5. Set environment variable:

```bash
export GOOGLE_CALENDAR_ID='your-calendar-id@group.calendar.google.com'
```

If not set, it defaults to `'primary'`.

### 8. Update Timezone (if needed)

Edit `services/calendar/google_calendar.py` and change the timezone on lines 115 and 119:

```python
'timeZone': 'America/New_York',  # Change to your timezone
```

Common timezones:
- `America/New_York` (EST/EDT)
- `America/Chicago` (CST/CDT)
- `America/Denver` (MST/MDT)
- `America/Los_Angeles` (PST/PDT)
- `Europe/London` (GMT/BST)
- [Full list of timezones](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones)

## Railway Deployment

For Railway, add the environment variables:

1. Go to your Railway project
2. Click on your service
3. Go to **Variables** tab
4. Add the following variables:
   ```
   GOOGLE_CALENDAR_CREDENTIALS_JSON = [paste entire JSON content]
   GOOGLE_CALENDAR_ID = your-calendar-id (optional)
   ```

**Important**: Make sure to paste the entire JSON content as one line, or Railway accepts multiline JSON in quotes.

## Testing

Once set up, you can test by calling your phone number and saying:
- "I'd like to schedule an appointment"
- "What times are available on Friday?"
- "Can I book a meeting for tomorrow at 2 PM?"

The AI will:
1. Ask for the preferred date
2. Check available slots
3. Offer available times
4. Collect customer information (name, email, phone)
5. Schedule the appointment
6. Confirm the booking

## Customization

### Business Hours

Edit `services/calendar/google_calendar.py` lines 55-56 to change business hours:

```python
start_time = target_date.replace(hour=9, minute=0)   # 9 AM start
end_time = target_date.replace(hour=17, minute=0)     # 5 PM end
```

### Appointment Duration

Default is 30 minutes. The AI will respect whatever duration is needed based on the conversation.

### Reminders

Edit `services/calendar/google_calendar.py` lines 121-125 to customize reminders:

```python
'overrides': [
    {'method': 'email', 'minutes': 24 * 60},  # 1 day before
    {'method': 'popup', 'minutes': 30},        # 30 minutes before
],
```

## Troubleshooting

### "Calendar service not initialized"
- Check that your credentials file exists and is valid JSON
- Verify the `GOOGLE_CALENDAR_CREDENTIALS_JSON` or `GOOGLE_CALENDAR_CREDENTIALS_FILE` environment variable is set correctly

### "Insufficient Permission" error
- Make sure you shared the calendar with the service account email
- Ensure the service account has "Make changes to events" permission

### No available slots showing
- Check that your business hours in the code match your expectations
- Verify the calendar doesn't have conflicting events
- Check that the timezone is set correctly

## Security Best Practices

1. **Never commit credentials to git** - Add `credentials.json` to `.gitignore`
2. **Use environment variables** in production
3. **Rotate keys periodically** through Google Cloud Console
4. **Limit service account permissions** to only what's needed

## Additional Features You Can Add

- Block out lunch hours
- Add different appointment types (15min, 30min, 1hr)
- Send SMS confirmations using Twilio
- Add buffer time between appointments
- Implement cancellation/rescheduling
- Add webhook notifications for new appointments

## Support

If you encounter issues:
1. Check the Railway logs for error messages
2. Verify all environment variables are set
3. Test the calendar API directly using Google's API Explorer
4. Ensure the service account has proper permissions

