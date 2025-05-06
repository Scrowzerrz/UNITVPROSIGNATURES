# Architecture Overview

## 1. Overview

UniTV is a subscription management system that provides TV streaming services. The system consists of two main interfaces:

1. A Telegram bot for user interactions (subscription purchasing, account management)
2. A web-based admin panel for administrative tasks

The application uses Flask as its web framework and stores data in JSON files rather than a traditional database. Authentication is handled via Telegram ID verification, and the system includes features like coupon management, referral rewards, and payment processing.

## 2. System Architecture

The system follows a monolithic architecture with clear separation between the bot interface and web interface, sharing common data models and utility functions:

```
┌─────────────────────────────┐
│         Flask App           │
├─────────────┬───────────────┤
│ Telegram Bot│  Admin Panel  │
│ Interface   │  Web Interface│
├─────────────┴───────────────┤
│     Shared Utils & Config   │
├─────────────────────────────┤
│      JSON File Storage      │
└─────────────────────────────┘
```

### Key Design Decisions

1. **Monolithic Architecture**: The application integrates both the Telegram bot and web admin panel in a single codebase, allowing for shared code and simplified deployment.

2. **JSON File Storage**: Rather than using a traditional database, the application stores data in JSON files. This approach simplifies deployment but may limit scalability for larger user bases.

3. **Telegram-based Authentication**: The system leverages Telegram's authentication system for user identity verification, reducing the need for custom account management.

## 3. Key Components

### 3.1 Web Application (Flask)

The web application provides an admin dashboard with the following features:
- User management
- Payment tracking
- Login credentials management
- Coupon creation and management
- System status monitoring

**Key Files**:
- `app.py`: Main Flask application handling routes and web functionality
- `main.py`: Entry point that starts both the web server and Telegram bot
- `templates/`: HTML templates for the web interface

### 3.2 Telegram Bot

The Telegram bot handles user interactions including:
- Subscription purchases
- Account management
- Payment verification
- Customer support

**Key Files**:
- `bot.py`: Implementation of the Telegram bot functionality
- Background tasks for monitoring subscription expirations and login availability

### 3.3 Shared Components

Several components are shared between the bot and web interfaces:

- **Configuration** (`config.py`): Centralized configuration including plan details, file paths, and system settings
- **Utilities** (`utils.py`): Shared functions for data manipulation, authentication, and business logic
- **Data Storage**: JSON files in the `data/` directory

### 3.4 Data Model

The application uses several JSON files to store data:
- `users.json`: User profiles and subscription details
- `payments.json`: Payment records and transaction history
- `logins.json`: Available login credentials organized by subscription plan
- `bot_config.json`: Bot settings including sales status, coupons, and referral rewards
- `auth.json`: Authentication data including admin and allowed Telegram IDs
- `sessions.json`: Web session management data

## 4. Data Flow

### 4.1 User Subscription Flow

1. User interacts with the Telegram bot to select a subscription plan
2. System generates a payment request
3. User completes payment
4. Admin approves payment via the web interface
5. System assigns login credentials from the available pool
6. User receives login details via Telegram

### 4.2 Admin Management Flow

1. Admin authenticates to the web interface using Telegram ID and an access code
2. Admin can view and manage users, payments, and login credentials
3. Admin can approve pending payments, add new login credentials, and create coupons
4. Changes are saved to the respective JSON data files

## 5. External Dependencies

### 5.1 Frontend
- Bootstrap CSS framework for responsive UI
- Font Awesome for icons
- DataTables for interactive tables
- Chart.js for analytics visualization

### 5.2 Backend
- Flask web framework
- PyTelegramBotAPI for Telegram bot functionality
- Gunicorn for WSGI HTTP server
- Werkzeug for security utilities

## 6. Deployment Strategy

The application is configured to run on Replit with the following setup:

- **Python 3.11** runtime environment
- **Gunicorn** as the WSGI HTTP server
- **PostgreSQL** support (though currently using JSON files for data storage)
- **Environment Variables** for sensitive configuration (Telegram bot token, admin IDs)

The deployment is configured through the `.replit` file, which defines:
- The required modules and packages
- A deployment target of "autoscale"
- Run commands for starting the application
- Port configuration (5000 internal, 80 external)

The application can be started in different ways:
1. Development mode: `python main.py` (runs both Flask app and Telegram bot)
2. Production mode: `gunicorn --bind 0.0.0.0:5000 main:app`

### 6.1 Scaling Considerations

The current architecture has some limitations for scaling:
- JSON file storage is not suitable for high concurrency or large datasets
- The monolithic design couples the bot and web interface
- No caching layer is implemented

Future improvements could include:
- Migrating to a proper database (PostgreSQL is already configured)
- Implementing a proper caching mechanism
- Separating the bot and web interface into microservices