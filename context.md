# Reporting WhatsApp Bot — Context

## Project Overview

The Reporting WhatsApp Bot is an internal automation system that collects business reports through WhatsApp, processes the submitted information, and generates structured summaries for management.

The primary goal is to make daily and weekly reporting faster, more consistent, and easier to monitor without requiring employees to manually prepare reports.

## Bot Name

Reporting Bot

## Primary Channel

WhatsApp

## Project Owner

Operations Team

## Target Users

- Sales executives
- Operations executives
- Team leads
- Regional managers
- Business managers

---

# Reporting Workflow

The standard reporting workflow is:

1. Employee sends a report through WhatsApp.
2. Bot identifies the employee.
3. Bot asks for missing information if required.
4. Submitted data is validated.
5. Report is stored in the reporting database.
6. Bot confirms successful submission.
7. Management dashboard/report is updated.
8. Daily summary is generated.

---

# Daily Report Structure

Each employee's daily report should contain:

- Employee name
- Employee ID
- Reporting date
- Region
- Team
- Total calls
- Connected calls
- Meetings completed
- Leads generated
- Deals closed
- Revenue generated
- Follow-ups pending
- Major achievement
- Major issue
- Plan for next working day

## Example Daily Report

**Employee:** Rahul Sharma  
**Employee ID:** EMP1024  
**Date:** 2026-10-08  
**Region:** West  
**Team:** Enterprise Sales

### Performance

- Calls Made: 42
- Connected Calls: 28
- Meetings: 6
- New Leads: 9
- Deals Closed: 2
- Revenue: ₹85,000
- Follow-ups Pending: 7

### Achievement

Closed two existing opportunities and generated nine new qualified leads.

### Issue

Three prospects requested additional pricing information before proceeding.

### Next Day Plan

- Follow up with pending prospects
- Conduct 4 scheduled meetings
- Contact 20 new prospects
- Prepare quotations for qualified leads

---

# WhatsApp Commands

The bot should understand commands such as:

`/report`

Start a new daily report.

`/status`

Show the user's current reporting status.

`/summary`

Show the user's recent performance summary.

`/pending`

Show pending follow-ups.

`/help`

Display available commands.

---

# Report Validation Rules

The bot should validate the following:

1. Calls made cannot be negative.
2. Connected calls cannot exceed total calls.
3. Meetings should normally not exceed connected calls.
4. Deals closed cannot be negative.
5. Revenue cannot be negative.
6. Reporting date must be valid.
7. Employee must be registered.
8. Required fields must be completed before submission.

If information is missing, the bot should ask for the missing field instead of rejecting the entire report.

---

# Daily Management Summary

At the end of each working day, the system should generate a management summary containing:

- Total employees who submitted reports
- Employees who have not submitted reports
- Total calls
- Total meetings
- Total leads
- Total deals
- Total revenue
- Top performers
- Major issues
- Follow-ups requiring attention

## Example Summary

**Daily Sales Report — 08 Oct 2026**

Employees Submitted: 42/47

### Overall Performance

- Total Calls: 1,842
- Connected Calls: 1,126
- Meetings: 214
- New Leads: 287
- Deals Closed: 38
- Revenue: ₹18.6L

### Top Performers

1. Rahul Sharma — ₹85,000
2. Priya Mehta — ₹72,000
3. Amit Kulkarni — ₹68,500

### Attention Required

- 5 employees have not submitted reports.
- 23 follow-ups are overdue.
- 7 high-value opportunities require management attention.

---

# Weekly Reporting

Every Monday, the bot should generate a summary for the previous week.

The weekly report should include:

- Total reports submitted
- Submission percentage
- Total calls
- Total meetings
- Total leads
- Total deals
- Total revenue
- Average revenue per employee
- Best-performing employee
- Best-performing team
- Week-over-week growth
- Outstanding follow-ups

---

# Example Weekly Summary

**Weekly Sales Report**

Period: 01 Oct 2026 – 07 Oct 2026

### Performance

- Reports Submitted: 218
- Submission Rate: 93%
- Calls: 8,742
- Meetings: 986
- Leads: 1,342
- Deals: 164
- Revenue: ₹74.8L

### Best Performer

Rahul Sharma

Revenue: ₹4.82L

### Best Team

West Enterprise Sales

Revenue: ₹18.4L

### Key Observation

Lead generation increased by approximately 12% compared with the previous week, while the conversion rate remained stable.

---

# Bot Response Guidelines

The bot should:

- Keep WhatsApp messages concise.
- Ask one question at a time when collecting reports.
- Confirm successful submissions.
- Clearly identify missing information.
- Use Indian currency formatting for INR values.
- Avoid exposing internal database information.
- Never modify a submitted report without user confirmation.
- Provide summaries in an easy-to-read format.

---

# Error Handling

If the reporting service is unavailable:

> "I'm unable to save your report right now. Please try again in a few minutes. Your information has not been submitted yet."

If an employee is not registered:

> "I couldn't find your employee account. Please contact the Operations Team to register your WhatsApp number."

If the report is incomplete:

> "Your report is missing the following information: Revenue generated. Please provide the revenue amount."

---

# Data Fields

| Field | Type | Required |
|---|---|---|
| Employee Name | Text | Yes |
| Employee ID | Text | Yes |
| Date | Date | Yes |
| Region | Text | Yes |
| Team | Text | Yes |
| Calls Made | Number | Yes |
| Connected Calls | Number | Yes |
| Meetings | Number | Yes |
| Leads | Number | Yes |
| Deals | Number | Yes |
| Revenue | Currency | Yes |
| Pending Follow-ups | Number | No |
| Achievement | Text | No |
| Issue | Text | No |
| Next Day Plan | Text | No |

---

# Future Improvements

Potential future features:

- Automated manager alerts
- AI-generated performance summaries
- Employee leaderboard
- WhatsApp voice reporting
- Automatic follow-up reminders
- CRM integration
- Google Sheets integration
- Dashboard integration
- Monthly performance reports
- Anomaly detection
- Report submission reminders

---

# Current Development Status

Status: Development / Testing

Current priority:

1. WhatsApp report collection
2. Data validation
3. GitHub-based context management
4. Automated reporting
5. Management summaries

Test environment should use dummy data only.

No production customer or employee information should be stored in the test repository.
