import json
import uuid
import time
import logging
import os
import secrets
import hashlib
from datetime import datetime, timedelta
from config import (
    USERS_FILE, PAYMENTS_FILE, LOGINS_FILE, BOT_CONFIG_FILE, AUTH_FILE, SESSION_FILE,
    PLANS, ADMIN_ID, SESSION_EXPIRY_HOURS
)

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Utility functions for file operations
def read_json_file(file_path):
    try:
        if not os.path.exists(file_path):
            if file_path == USERS_FILE:
                return {}
            elif file_path == PAYMENTS_FILE:
                return {}
            elif file_path == LOGINS_FILE:
                return {'30_days': [], '6_months': [], '1_year': []}
            elif file_path == BOT_CONFIG_FILE:
                return {'sales_enabled': True, 'warning_sent': False, 'sales_suspended_time': None, 'coupons': {}, 
                        'referral_rewards': {'referrer_discount': 10, 'referred_discount': 5, 'free_month_after_referrals': 3}}
        
        with open(file_path, 'r', encoding='utf-8') as file:
            return json.load(file)
    except Exception as e:
        logger.error(f"Error reading file {file_path}: {e}")
        # Return empty default based on file type
        if file_path == USERS_FILE or file_path == PAYMENTS_FILE:
            return {}
        elif file_path == LOGINS_FILE:
            return {'30_days': [], '6_months': [], '1_year': []}
        elif file_path == BOT_CONFIG_FILE:
            return {'sales_enabled': True, 'warning_sent': False, 'sales_suspended_time': None, 'coupons': {}, 
                    'referral_rewards': {'referrer_discount': 10, 'referred_discount': 5, 'free_month_after_referrals': 3}}

def write_json_file(file_path, data):
    try:
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, 'w', encoding='utf-8') as file:
            json.dump(data, file, indent=4, ensure_ascii=False)
        return True
    except Exception as e:
        logger.error(f"Error writing to file {file_path}: {e}")
        return False

# User management functions
def get_user(user_id):
    users = read_json_file(USERS_FILE)
    return users.get(str(user_id))

def save_user(user_id, user_data):
    users = read_json_file(USERS_FILE)
    users[str(user_id)] = user_data
    write_json_file(USERS_FILE, users)

def create_user(user_id, username, first_name, last_name=None, referred_by=None):
    user_data = {
        'username': username,
        'first_name': first_name,
        'last_name': last_name,
        'created_at': datetime.now().isoformat(),
        'has_active_plan': False,
        'plan_type': None,
        'plan_expiration': None,
        'login_info': None,
        'is_first_buy': True,
        'referrals': [],
        'referred_by': referred_by,
        'successful_referrals': 0
    }
    save_user(user_id, user_data)
    return user_data

# Payment management functions
def create_payment(user_id, plan_type, amount, coupon_code=None):
    payment_id = str(uuid.uuid4())
    payments = read_json_file(PAYMENTS_FILE)
    
    payment_data = {
        'payment_id': payment_id,
        'user_id': str(user_id),
        'plan_type': plan_type,
        'amount': amount,
        'original_amount': amount,
        'coupon_code': coupon_code,
        'status': 'pending',
        'created_at': datetime.now().isoformat(),
        'approved_at': None,
        'payer_name': '',
        'login_delivered': False
    }
    
    payments[payment_id] = payment_data
    write_json_file(PAYMENTS_FILE, payments)
    return payment_id

def get_payment(payment_id):
    payments = read_json_file(PAYMENTS_FILE)
    return payments.get(payment_id)

def update_payment(payment_id, data):
    payments = read_json_file(PAYMENTS_FILE)
    if payment_id in payments:
        payments[payment_id].update(data)
        write_json_file(PAYMENTS_FILE, payments)
        return True
    return False

def get_user_pending_payment(user_id):
    payments = read_json_file(PAYMENTS_FILE)
    for payment_id, payment in payments.items():
        if payment['user_id'] == str(user_id) and payment['status'] == 'pending':
            return payment
    return None

def cancel_payment(payment_id):
    payments = read_json_file(PAYMENTS_FILE)
    if payment_id in payments:
        payments[payment_id]['status'] = 'cancelled'
        write_json_file(PAYMENTS_FILE, payments)
        return True
    return False

# Login management functions
def add_login(plan_type, login_data):
    logins = read_json_file(LOGINS_FILE)
    if plan_type in logins:
        logins[plan_type].append(login_data)
        write_json_file(LOGINS_FILE, logins)
        return True
    return False

def get_available_login(plan_type):
    logins = read_json_file(LOGINS_FILE)
    if plan_type in logins and logins[plan_type]:
        return logins[plan_type][0]
    return None

def remove_login(plan_type, login_data):
    logins = read_json_file(LOGINS_FILE)
    if plan_type in logins and login_data in logins[plan_type]:
        logins[plan_type].remove(login_data)
        write_json_file(LOGINS_FILE, logins)
        return True
    return False

def assign_login_to_user(user_id, plan_type, payment_id):
    user = get_user(user_id)
    login = get_available_login(plan_type)
    
    if not user:
        logger.error(f"User {user_id} not found")
        return False
    
    if not login:
        logger.error(f"No available login for plan type {plan_type}")
        return False
    
    # Update user with the login and plan information
    plan_info = PLANS[plan_type]
    expiration_date = datetime.now() + timedelta(days=plan_info['duration_days'])
    
    user['has_active_plan'] = True
    user['plan_type'] = plan_type
    user['plan_expiration'] = expiration_date.isoformat()
    user['login_info'] = login
    user['is_first_buy'] = False
    
    save_user(user_id, user)
    
    # Update payment status
    update_payment(payment_id, {
        'status': 'completed',
        'approved_at': datetime.now().isoformat(),
        'login_delivered': True
    })
    
    # Remove the login from available logins
    remove_login(plan_type, login)
    
    # Process referral if applicable
    if user['referred_by']:
        process_successful_referral(user['referred_by'])
    
    return login

def process_successful_referral(referrer_id):
    referrer = get_user(referrer_id)
    if referrer:
        referrer['successful_referrals'] = referrer.get('successful_referrals', 0) + 1
        save_user(referrer_id, referrer)
        
        # Check if referrer qualifies for free month
        bot_config = read_json_file(BOT_CONFIG_FILE)
        required_referrals = bot_config['referral_rewards']['free_month_after_referrals']
        
        if referrer['successful_referrals'] % required_referrals == 0:
            # Will be used by the bot to notify about free month
            return True
    
    return False

# Check for pending logins and users waiting for logins
def get_pending_approvals():
    payments = read_json_file(PAYMENTS_FILE)
    pending_approvals = []
    
    for payment_id, payment in payments.items():
        if payment['status'] == 'pending' and payment.get('payer_name'):
            pending_approvals.append(payment)
    
    return pending_approvals

def get_users_waiting_for_login():
    payments = read_json_file(PAYMENTS_FILE)
    waiting_users = []
    
    for payment_id, payment in payments.items():
        if payment['status'] == 'approved' and not payment['login_delivered']:
            waiting_users.append(payment)
    
    return waiting_users

# Functions to check and update sales status
def check_should_suspend_sales():
    logins = read_json_file(LOGINS_FILE)
    total_logins = sum(len(logins[plan_type]) for plan_type in logins)
    
    if total_logins == 0:
        return True
    
    return False

def suspend_sales():
    bot_config = read_json_file(BOT_CONFIG_FILE)
    bot_config['sales_enabled'] = False
    bot_config['sales_suspended_time'] = datetime.now().isoformat()
    write_json_file(BOT_CONFIG_FILE, bot_config)

def resume_sales():
    bot_config = read_json_file(BOT_CONFIG_FILE)
    bot_config['sales_enabled'] = True
    bot_config['sales_suspended_time'] = None
    bot_config['warning_sent'] = False
    write_json_file(BOT_CONFIG_FILE, bot_config)

def sales_enabled():
    bot_config = read_json_file(BOT_CONFIG_FILE)
    return bot_config.get('sales_enabled', True)

# Coupon management functions
def add_coupon(code, discount_type, discount_value, expiration_date, max_uses, min_purchase, applicable_plans):
    bot_config = read_json_file(BOT_CONFIG_FILE)
    
    # Convert to uppercase for consistency
    code = code.upper()
    
    # Check if coupon already exists
    if code in bot_config.get('coupons', {}):
        return False, "Cupom já existe."
    
    # Check valid discount value
    if discount_type == 'percentage' and (discount_value <= 0 or discount_value >= 100):
        return False, "Valor de desconto percentual deve estar entre 1 e 99."
    
    if discount_type == 'fixed' and discount_value <= 0:
        return False, "Valor de desconto fixo deve ser maior que zero."
    
    # Don't allow 100% discount
    if discount_type == 'percentage' and discount_value == 100:
        return False, "Cupons com 100% de desconto não são permitidos."
    
    # Create the coupon
    coupon = {
        'code': code,
        'discount_type': discount_type,
        'discount_value': discount_value,
        'expiration_date': expiration_date,
        'max_uses': max_uses,
        'min_purchase': min_purchase,
        'applicable_plans': applicable_plans,
        'uses': 0,
        'users': []
    }
    
    if 'coupons' not in bot_config:
        bot_config['coupons'] = {}
    
    bot_config['coupons'][code] = coupon
    write_json_file(BOT_CONFIG_FILE, bot_config)
    
    return True, "Cupom criado com sucesso."

def validate_coupon(code, user_id, plan_type, amount):
    if not code:
        return None, "Código de cupom não fornecido."
    
    code = code.upper()
    bot_config = read_json_file(BOT_CONFIG_FILE)
    
    if 'coupons' not in bot_config or code not in bot_config['coupons']:
        return None, "Cupom não encontrado."
    
    coupon = bot_config['coupons'][code]
    
    # Check expiration
    if coupon['expiration_date']:
        expiration_date = datetime.fromisoformat(coupon['expiration_date'])
        if datetime.now() > expiration_date:
            return None, "Este cupom expirou."
    
    # Check max uses
    if coupon['max_uses'] != -1 and coupon['uses'] >= coupon['max_uses']:
        return None, "Este cupom atingiu o limite máximo de usos."
    
    # Check user already used
    if str(user_id) in coupon['users']:
        return None, "Você já utilizou este cupom anteriormente."
    
    # Check minimum purchase
    if coupon['min_purchase'] and amount < coupon['min_purchase']:
        return None, f"Valor mínimo para uso do cupom é R$ {coupon['min_purchase']:.2f}."
    
    # Check applicable plans
    if 'all' not in coupon['applicable_plans'] and plan_type not in coupon['applicable_plans']:
        return None, "Este cupom não é válido para o plano selecionado."
    
    # Check if it's the user's first purchase
    user = get_user(user_id)
    if user and user.get('is_first_buy', True):
        return None, "Cupons não podem ser usados na primeira compra."
    
    # Calculate discount
    if coupon['discount_type'] == 'percentage':
        discount = amount * (coupon['discount_value'] / 100)
    else:  # fixed
        discount = coupon['discount_value']
    
    # Ensure discount doesn't make price negative
    if amount - discount <= 0:
        discount = amount - 0.01  # Leave minimal price to pay
    
    return {
        'code': code,
        'discount': discount,
        'final_amount': amount - discount
    }, "Cupom aplicado com sucesso!"

def use_coupon(code, user_id):
    code = code.upper()
    bot_config = read_json_file(BOT_CONFIG_FILE)
    
    if 'coupons' in bot_config and code in bot_config['coupons']:
        coupon = bot_config['coupons'][code]
        coupon['uses'] += 1
        coupon['users'].append(str(user_id))
        write_json_file(BOT_CONFIG_FILE, bot_config)
        return True
    
    return False

def delete_coupon(code):
    code = code.upper()
    bot_config = read_json_file(BOT_CONFIG_FILE)
    
    if 'coupons' in bot_config and code in bot_config['coupons']:
        del bot_config['coupons'][code]
        write_json_file(BOT_CONFIG_FILE, bot_config)
        return True
    
    return False

# Check for expiring subscriptions
def get_expiring_subscriptions(days_threshold=3):
    users = read_json_file(USERS_FILE)
    expiring_users = []
    
    for user_id, user_data in users.items():
        if user_data.get('has_active_plan') and user_data.get('plan_expiration'):
            expiration_date = datetime.fromisoformat(user_data['plan_expiration'])
            days_left = (expiration_date - datetime.now()).days
            
            if 0 < days_left <= days_threshold:
                expiring_users.append({
                    'user_id': user_id,
                    'days_left': days_left,
                    'plan_type': user_data['plan_type'],
                    'expiration_date': user_data['plan_expiration']
                })
    
    return expiring_users

# Format currency values
def format_currency(value):
    return f"R$ {value:.2f}".replace('.', ',')

# Calculate price based on user status and plan
def calculate_plan_price(user_id, plan_type):
    user = get_user(user_id)
    plan = PLANS[plan_type]
    
    # Check if user is eligible for first-time buyer discount
    if user and user.get('is_first_buy') and plan['first_buy_discount']:
        return plan['first_buy_price']
    
    return plan['regular_price']

# Apply referral discount if applicable
def apply_referral_discount(user_id, amount):
    user = get_user(user_id)
    bot_config = read_json_file(BOT_CONFIG_FILE)
    
    if not user or user.get('is_first_buy'):
        return amount, False
    
    referrer_discount = bot_config['referral_rewards']['referrer_discount']
    
    # Check if this user was referred and it's their first non-first purchase
    if user.get('referred_by') and not user.get('referral_discount_applied'):
        # Apply discount
        discount = (referrer_discount / 100) * amount
        final_amount = amount - discount
        
        # Mark as applied
        user['referral_discount_applied'] = True
        save_user(user_id, user)
        
        return final_amount, True
    
    return amount, False

# Telegram Authentication Functions
def is_admin_telegram_id(telegram_id):
    """Check if a Telegram ID is an admin"""
    auth_data = read_json_file(AUTH_FILE)
    return str(telegram_id) in auth_data.get('admin_telegram_ids', [])

def is_allowed_telegram_id(telegram_id):
    """Check if a Telegram ID is allowed to access the admin panel"""
    auth_data = read_json_file(AUTH_FILE)
    return (str(telegram_id) in auth_data.get('allowed_telegram_ids', []) or 
            is_admin_telegram_id(telegram_id))

def add_allowed_telegram_id(telegram_id):
    """Add a Telegram ID to the allowed list"""
    auth_data = read_json_file(AUTH_FILE)
    telegram_id = str(telegram_id)
    
    if 'allowed_telegram_ids' not in auth_data:
        auth_data['allowed_telegram_ids'] = []
    
    if telegram_id not in auth_data['allowed_telegram_ids']:
        auth_data['allowed_telegram_ids'].append(telegram_id)
        write_json_file(AUTH_FILE, auth_data)
        return True
    
    return False

def remove_allowed_telegram_id(telegram_id):
    """Remove a Telegram ID from the allowed list"""
    auth_data = read_json_file(AUTH_FILE)
    telegram_id = str(telegram_id)
    
    if 'allowed_telegram_ids' in auth_data and telegram_id in auth_data['allowed_telegram_ids']:
        auth_data['allowed_telegram_ids'].remove(telegram_id)
        write_json_file(AUTH_FILE, auth_data)
        return True
    
    return False

# Session Management Functions
def create_session(telegram_id, user_data=None):
    """Create a new session for a user"""
    session_token = secrets.token_hex(32)
    sessions = read_json_file(SESSION_FILE)
    
    if not user_data:
        # Verificar se o usuário existe, se não, criar dados básicos
        user = get_user(telegram_id)
        if user:
            user_data = {
                'first_name': user.get('first_name', 'Unknown'),
                'username': user.get('username', 'Unknown')
            }
        else:
            # Usuário não encontrado, usar dados básicos
            user_data = {
                'first_name': 'Admin',
                'username': f'User{telegram_id}'
            }
    
    # Create session
    sessions[session_token] = {
        'telegram_id': str(telegram_id),
        'created_at': datetime.now().isoformat(),
        'expires_at': (datetime.now() + timedelta(hours=SESSION_EXPIRY_HOURS)).isoformat(),
        'user_data': user_data
    }
    
    write_json_file(SESSION_FILE, sessions)
    return session_token

def get_session(session_token):
    """Get a session by token"""
    sessions = read_json_file(SESSION_FILE)
    session = sessions.get(session_token)
    
    if not session:
        return None
    
    # Check if session is expired
    expires_at = datetime.fromisoformat(session['expires_at'])
    if datetime.now() > expires_at:
        delete_session(session_token)
        return None
    
    return session

def delete_session(session_token):
    """Delete a session"""
    sessions = read_json_file(SESSION_FILE)
    if session_token in sessions:
        del sessions[session_token]
        write_json_file(SESSION_FILE, sessions)
        return True
    
    return False

def clean_expired_sessions():
    """Remove all expired sessions"""
    sessions = read_json_file(SESSION_FILE)
    now = datetime.now()
    
    session_tokens_to_delete = []
    for token, session in sessions.items():
        expires_at = datetime.fromisoformat(session['expires_at'])
        if now > expires_at:
            session_tokens_to_delete.append(token)
    
    for token in session_tokens_to_delete:
        del sessions[token]
    
    if session_tokens_to_delete:
        write_json_file(SESSION_FILE, sessions)
    
    return len(session_tokens_to_delete)

# Authentication token functions
def create_auth_token(telegram_id):
    """Create a one-time authentication token for a Telegram user"""
    # Generate a secure random token
    token = secrets.token_hex(16)
    
    # Create hash of the token to store
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    
    # Get current user data
    user = get_user(telegram_id)
    
    if user:
        # Update user with token hash and expiration
        user['auth_token'] = {
            'hash': token_hash,
            'expires_at': (datetime.now() + timedelta(minutes=10)).isoformat()
        }
        save_user(telegram_id, user)
        
        return token
    
    return None

def verify_auth_token(telegram_id, token):
    """Verify a one-time authentication token"""
    user = get_user(telegram_id)
    
    if not user or 'auth_token' not in user:
        return False
    
    token_data = user['auth_token']
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    
    # Check if token has expired
    expires_at = datetime.fromisoformat(token_data['expires_at'])
    if datetime.now() > expires_at:
        # Clear expired token
        user.pop('auth_token', None)
        save_user(telegram_id, user)
        return False
    
    # Check if token hash matches
    if token_hash == token_data['hash']:
        # Clear used token
        user.pop('auth_token', None)
        save_user(telegram_id, user)
        return True
    
    return False

# Functions to check admin and allowed user status
def is_admin_telegram_id(telegram_id):
    """Check if a Telegram ID is an admin"""
    auth_data = read_json_file(AUTH_FILE)
    
    # Convert to string for comparison since JSON keys are strings
    telegram_id = str(telegram_id)
    
    # Check primary admin ID from environment variable
    if telegram_id == str(ADMIN_ID):
        return True
    
    # Check admin list in auth.json
    if 'admin_telegram_ids' in auth_data:
        return telegram_id in auth_data['admin_telegram_ids']
        
    return False

def is_allowed_telegram_id(telegram_id):
    """Check if a Telegram ID is allowed to access the admin panel"""
    # Admins always have access
    if is_admin_telegram_id(telegram_id):
        return True
    
    auth_data = read_json_file(AUTH_FILE)
    
    # Convert to string for comparison since JSON keys are strings
    telegram_id = str(telegram_id)
    
    # Check allowed user list
    if 'allowed_telegram_ids' in auth_data:
        return telegram_id in auth_data['allowed_telegram_ids']
        
    return False

def add_allowed_telegram_id(telegram_id):
    """Add a Telegram ID to the allowed list"""
    auth_data = read_json_file(AUTH_FILE)
    
    # Convert to string for storage consistency
    telegram_id = str(telegram_id)
    
    # Check if it's already an admin
    if is_admin_telegram_id(telegram_id):
        return False
    
    # Ensure the allowed_telegram_ids list exists
    if 'allowed_telegram_ids' not in auth_data:
        auth_data['allowed_telegram_ids'] = []
    
    # Add to allowed list if not already there
    if telegram_id not in auth_data['allowed_telegram_ids']:
        auth_data['allowed_telegram_ids'].append(telegram_id)
        write_json_file(AUTH_FILE, auth_data)
        return True
        
    return False

def remove_allowed_telegram_id(telegram_id):
    """Remove a Telegram ID from the allowed list"""
    auth_data = read_json_file(AUTH_FILE)
    
    # Convert to string for consistency
    telegram_id = str(telegram_id)
    
    # Cannot remove admins
    if is_admin_telegram_id(telegram_id):
        return False
    
    # Remove from allowed list if present
    if 'allowed_telegram_ids' in auth_data and telegram_id in auth_data['allowed_telegram_ids']:
        auth_data['allowed_telegram_ids'].remove(telegram_id)
        write_json_file(AUTH_FILE, auth_data)
        return True
        
    return False

# Access code functions for admin panel login
def generate_access_code(telegram_id, expiration_hours=24):
    """
    Generate a unique access code for a Telegram ID
    
    This creates a 6-character alphanumeric code that can be used for login
    This code is stored in the auth.json file and expires after a set time
    """
    # Generate a random 6-character code
    code = ''.join(secrets.choice('ABCDEFGHJKLMNPQRSTUVWXYZ23456789') for _ in range(6))
    
    # Convert to string for storage
    telegram_id = str(telegram_id)
    
    auth_data = read_json_file(AUTH_FILE)
    
    # Initialize access_codes dict if it doesn't exist
    if 'access_codes' not in auth_data:
        auth_data['access_codes'] = {}
    
    # Check if user already has previous codes and remove them
    for existing_code in list(auth_data['access_codes'].keys()):
        if auth_data['access_codes'][existing_code].get('telegram_id') == telegram_id:
            del auth_data['access_codes'][existing_code]
    
    # Store the code with expiration time
    auth_data['access_codes'][code] = {
        'telegram_id': telegram_id,
        'created_at': datetime.now().isoformat(),
        'expires_at': (datetime.now() + timedelta(hours=expiration_hours)).isoformat()
    }
    
    write_json_file(AUTH_FILE, auth_data)
    
    return code

def verify_access_code(telegram_id, code):
    """
    Verify if an access code is valid for the given Telegram ID
    
    Returns True if the code is valid and not expired, False otherwise
    """
    auth_data = read_json_file(AUTH_FILE)
    
    # Convert to string for comparison
    telegram_id = str(telegram_id)
    
    # Check if access_codes exists
    if 'access_codes' not in auth_data:
        return False
    
    # Check if code exists
    if code not in auth_data['access_codes']:
        return False
    
    # Get code data
    code_data = auth_data['access_codes'][code]
    
    # Check if telegram_id matches
    if code_data.get('telegram_id') != telegram_id:
        return False
    
    # Check if code is expired
    expires_at = datetime.fromisoformat(code_data['expires_at'])
    if datetime.now() > expires_at:
        # Remove expired code
        del auth_data['access_codes'][code]
        write_json_file(AUTH_FILE, auth_data)
        return False
    
    # Valid code - remove it after use (one-time use)
    del auth_data['access_codes'][code]
    write_json_file(AUTH_FILE, auth_data)
    
    return True

def list_active_access_codes():
    """
    List all active access codes
    
    Returns a dictionary with code -> user info mapping
    Removes expired codes in the process
    """
    auth_data = read_json_file(AUTH_FILE)
    
    if 'access_codes' not in auth_data:
        auth_data['access_codes'] = {}
        return {}
    
    # Check for expired codes and remove them
    now = datetime.now()
    codes_to_remove = []
    
    for code, code_data in auth_data['access_codes'].items():
        expires_at = datetime.fromisoformat(code_data['expires_at'])
        if now > expires_at:
            codes_to_remove.append(code)
    
    # Remove expired codes
    for code in codes_to_remove:
        del auth_data['access_codes'][code]
    
    # If we removed any codes, update the file
    if codes_to_remove:
        write_json_file(AUTH_FILE, auth_data)
    
    # Return active codes
    active_codes = {}
    for code, code_data in auth_data['access_codes'].items():
        # Get user info
        user = get_user(code_data['telegram_id'])
        username = user.get('username', 'Unknown') if user else 'Unknown'
        
        active_codes[code] = {
            'telegram_id': code_data['telegram_id'],
            'username': username,
            'created_at': code_data['created_at'],
            'expires_at': code_data['expires_at']
        }
    
    return active_codes
