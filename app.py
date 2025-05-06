import os
import json
import logging
import secrets
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, abort
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from config import (
    USERS_FILE, PAYMENTS_FILE, LOGINS_FILE, BOT_CONFIG_FILE, AUTH_FILE, SESSION_FILE,
    PLANS, ADMIN_ID, SESSION_EXPIRY_HOURS
)
from utils import (
    read_json_file, write_json_file, add_login, add_coupon, delete_coupon,
    resume_sales, suspend_sales, sales_enabled, format_currency, create_auth_token, verify_auth_token,
    is_admin_telegram_id, is_allowed_telegram_id, create_session, get_session, delete_session,
    generate_access_code, verify_access_code, list_active_access_codes
)

# Configure logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Adicionar logs detalhados para depuração
import sys
import traceback

def log_exception(e):
    """Log a detailed exception message"""
    exc_type, exc_value, exc_traceback = sys.exc_info()
    tb_lines = traceback.format_exception(exc_type, exc_value, exc_traceback)
    logger.error("Exception details: %s", ''.join(tb_lines))

# Initialize Flask app
app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "unitv_secret_key")

# Login required decorator
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Check if user is logged in
        if 'logged_in' not in session:
            return redirect(url_for('login', next=request.url))
        
        # Verify session token if available
        if 'session_token' in session:
            session_data = get_session(session['session_token'])
            if not session_data:
                # Session expired or invalid, clear session and redirect to login
                session.clear()
                flash('Sua sessão expirou. Por favor, faça login novamente.', 'warning')
                return redirect(url_for('login', next=request.url))
            
            # Check if the user still has permission
            telegram_id = session.get('telegram_id')
            if telegram_id and not is_allowed_telegram_id(telegram_id):
                # User no longer has permission
                delete_session(session['session_token'])
                session.clear()
                flash('Você não tem mais permissão para acessar o painel administrativo.', 'danger')
                return redirect(url_for('login'))
        else:
            # No session token found but logged_in is True (old session)
            session.clear()
            flash('Sessão inválida. Por favor, faça login novamente.', 'warning')
            return redirect(url_for('login', next=request.url))
            
        return f(*args, **kwargs)
    return decorated_function

# Routes
@app.route('/')
def index():
    if 'logged_in' in session:
        return redirect(url_for('dashboard'))
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    try:
        # Check if already logged in
        if 'logged_in' in session:
            return redirect(url_for('dashboard'))
        
        # Handle the POST request (form submission with ID and access code)
        if request.method == 'POST':
            telegram_id = request.form.get('telegram_id')
            access_code = request.form.get('access_code')
            
            logger.debug(f"Login attempt with Telegram ID: {telegram_id}, Access Code: {access_code}")
            
            if not telegram_id or not access_code:
                flash('Por favor, preencha o ID do Telegram e o código de acesso.', 'warning')
                return render_template('login.html')
                
            # Verify access code for this telegram ID
            try:
                is_valid = verify_access_code(telegram_id, access_code)
                logger.debug(f"Access code validation result: {is_valid}")
                
                if is_valid:
                    # Check if user is admin or allowed
                    is_admin = is_admin_telegram_id(telegram_id)
                    is_allowed = is_allowed_telegram_id(telegram_id)
                    logger.debug(f"User permissions - Admin: {is_admin}, Allowed: {is_allowed}")
                    
                    if is_admin or is_allowed:
                        # Create new session
                        session_token = create_session(telegram_id)
                        session['logged_in'] = True
                        session['session_token'] = session_token
                        session['telegram_id'] = telegram_id
                        
                        # Log the successful login
                        logger.info(f"Login successful for Telegram ID: {telegram_id}")
                        
                        flash('Login realizado com sucesso!', 'success')
                        # Corrigido o redirecionamento para evitar problemas com o parâmetro next
                        next_page = request.args.get('next')
                        if next_page and next_page.startswith('/') and not next_page.startswith('//'):
                            return redirect(next_page)
                        return redirect(url_for('dashboard'))
                    else:
                        # Log the unauthorized access attempt
                        logger.warning(f"Unauthorized access attempt from Telegram ID: {telegram_id}")
                        flash('Seu ID do Telegram não tem permissão para acessar o painel administrativo.', 'danger')
                else:
                    logger.warning(f"Invalid access code attempt: {access_code} for Telegram ID: {telegram_id}")
                    flash('Código de acesso inválido ou expirado.', 'danger')
            except Exception as e:
                log_exception(e)
                logger.error(f"Error during access code verification: {e}")
                flash('Erro ao verificar o código de acesso. Tente novamente.', 'danger')
        
        # If this is a GET request or authentication failed, show login page
        return render_template('login.html')
    except Exception as e:
        log_exception(e)
        flash('Erro no processo de login. Por favor, tente novamente.', 'danger')
        return render_template('login.html')

@app.route('/logout')
def logout():
    # Delete session token if exists
    if 'session_token' in session:
        delete_session(session['session_token'])
    
    # Clear all session data
    session.pop('logged_in', None)
    session.pop('session_token', None)
    session.pop('telegram_id', None)
    
    flash('Você saiu com sucesso. Para acessar novamente, use o bot do Telegram.', 'success')
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    try:
        # Get data for dashboard
        users = read_json_file(USERS_FILE) or {}
        payments = read_json_file(PAYMENTS_FILE) or {}
        logins = read_json_file(LOGINS_FILE) or {}
        bot_config = read_json_file(BOT_CONFIG_FILE) or {}
        
        # Count active users
        active_users = 0
        for user_id, user_data in users.items():
            if user_data and user_data.get('has_active_plan'):
                active_users += 1
        
        # Count pending payments
        pending_payments = 0
        for payment_id, payment_data in payments.items():
            if payment_data and payment_data.get('status') == 'pending_approval':
                pending_payments += 1
        
        # Count available logins
        available_logins = {
            '30_days': len(logins.get('30_days', [])),
            '6_months': len(logins.get('6_months', [])),
            '1_year': len(logins.get('1_year', []))
        }
        
        # Count total pending approvals
        pending_approvals = 0
        for payment_id, payment_data in payments.items():
            if payment_data and payment_data.get('status') == 'pending_approval':
                pending_approvals += 1
        
        # Count users waiting for logins
        waiting_for_login = 0
        for payment_id, payment_data in payments.items():
            if payment_data and payment_data.get('status') == 'approved' and not payment_data.get('login_delivered'):
                waiting_for_login += 1
        
        # Sales status
        sales_status = bot_config.get('sales_enabled', True)
        
        # Coupons
        coupons = bot_config.get('coupons', {})
        active_coupons = len(coupons) if coupons else 0
        
        stats = {
            'total_users': len(users),
            'active_users': active_users,
            'pending_payments': pending_payments,
            'available_logins': available_logins,
            'pending_approvals': pending_approvals,
            'waiting_for_login': waiting_for_login,
            'sales_status': sales_status,
            'active_coupons': active_coupons
        }
        
        logger.debug(f"Dashboard loaded with stats: {stats}")
        return render_template('dashboard.html', stats=stats)
    except Exception as e:
        log_exception(e)
        flash('Erro ao carregar o painel. Tente novamente.', 'danger')
        return render_template('dashboard.html', stats={
            'total_users': 0,
            'active_users': 0,
            'pending_payments': 0,
            'available_logins': {'30_days': 0, '6_months': 0, '1_year': 0},
            'pending_approvals': 0,
            'waiting_for_login': 0,
            'sales_status': True,
            'active_coupons': 0
        })

@app.route('/users')
@login_required
def users():
    try:
        users_data = read_json_file(USERS_FILE) or {}
        return render_template('users.html', users=users_data)
    except Exception as e:
        log_exception(e)
        flash('Erro ao carregar usuários. Tente novamente.', 'danger')
        return render_template('users.html', users={})

@app.route('/users/<user_id>')
@login_required
def user_detail(user_id):
    try:
        users_data = read_json_file(USERS_FILE) or {}
        user = users_data.get(user_id)
        
        if not user:
            flash('Usuário não encontrado', 'danger')
            return redirect(url_for('users'))
        
        # Find user's payments
        payments_data = read_json_file(PAYMENTS_FILE) or {}
        user_payments = []
        
        for payment_id, payment in payments_data.items():
            if payment and payment.get('user_id') == user_id:
                payment_copy = payment.copy()  # Criar uma cópia para não modificar o original
                payment_copy['id'] = payment_id
                user_payments.append(payment_copy)
        
        # Sort payments by date
        if user_payments:
            user_payments.sort(key=lambda x: x.get('created_at', ''), reverse=True)
        
        return render_template('users.html', user=user, user_id=user_id, payments=user_payments)
    except Exception as e:
        log_exception(e)
        flash('Erro ao carregar detalhes do usuário. Tente novamente.', 'danger')
        return redirect(url_for('users'))

@app.route('/payments')
@login_required
def payments():
    try:
        payments_data = read_json_file(PAYMENTS_FILE) or {}
        users_data = read_json_file(USERS_FILE) or {}
        
        # Add user info to payments
        payments_list = []
        for payment_id, payment in payments_data.items():
            if payment:
                payment_copy = payment.copy()  # Criar uma cópia para não modificar o original
                user_id = payment.get('user_id')
                user = users_data.get(user_id, {})
                payment_copy['username'] = user.get('username', 'Desconhecido')
                payment_copy['first_name'] = user.get('first_name', 'Desconhecido')
                payment_copy['id'] = payment_id
                payments_list.append(payment_copy)
        
        # Sort by date
        if payments_list:
            payments_list.sort(key=lambda x: x.get('created_at', ''), reverse=True)
        
        return render_template('payments.html', payments=payments_list)
    except Exception as e:
        log_exception(e)
        flash('Erro ao carregar pagamentos. Tente novamente.', 'danger')
        return render_template('payments.html', payments=[])

@app.route('/payments/approve/<payment_id>', methods=['POST'])
@login_required
def approve_payment(payment_id):
    payments_data = read_json_file(PAYMENTS_FILE)
    payment = payments_data.get(payment_id)
    
    if not payment:
        flash('Payment not found', 'danger')
        return redirect(url_for('payments'))
    
    payment['status'] = 'approved'
    payment['approved_at'] = datetime.now().isoformat()
    
    write_json_file(PAYMENTS_FILE, payments_data)
    flash('Payment approved', 'success')
    
    return redirect(url_for('payments'))

@app.route('/payments/reject/<payment_id>', methods=['POST'])
@login_required
def reject_payment(payment_id):
    payments_data = read_json_file(PAYMENTS_FILE)
    payment = payments_data.get(payment_id)
    
    if not payment:
        flash('Payment not found', 'danger')
        return redirect(url_for('payments'))
    
    payment['status'] = 'rejected'
    
    write_json_file(PAYMENTS_FILE, payments_data)
    flash('Payment rejected', 'success')
    
    return redirect(url_for('payments'))

@app.route('/logins')
@login_required
def logins():
    logins_data = read_json_file(LOGINS_FILE)
    return render_template('logins.html', logins=logins_data, plans=PLANS)

@app.route('/logins/add', methods=['POST'])
@login_required
def add_login_route():
    login_data = request.form.get('login')
    plan_type = request.form.get('plan_type')
    
    if not login_data or not plan_type:
        flash('Login data and plan type are required', 'danger')
        return redirect(url_for('logins'))
    
    if plan_type not in PLANS:
        flash('Invalid plan type', 'danger')
        return redirect(url_for('logins'))
    
    # Add login
    success = add_login(plan_type, login_data)
    
    if success:
        flash('Login added successfully', 'success')
    else:
        flash('Error adding login', 'danger')
    
    return redirect(url_for('logins'))

@app.route('/logins/add-batch', methods=['POST'])
@login_required
def add_login_batch():
    login_data = request.form.get('logins')
    plan_type = request.form.get('plan_type')
    
    if not login_data or not plan_type:
        flash('Login data and plan type are required', 'danger')
        return redirect(url_for('logins'))
    
    if plan_type not in PLANS:
        flash('Invalid plan type', 'danger')
        return redirect(url_for('logins'))
    
    # Split logins by line
    logins_list = login_data.strip().split('\n')
    
    # Add each login
    added = 0
    for login in logins_list:
        login = login.strip()
        if login:
            success = add_login(plan_type, login)
            if success:
                added += 1
    
    flash(f'Added {added} logins successfully', 'success')
    return redirect(url_for('logins'))

@app.route('/logins/remove', methods=['POST'])
@login_required
def remove_login():
    login_data = request.form.get('login')
    plan_type = request.form.get('plan_type')
    
    if not login_data or not plan_type:
        return jsonify({'success': False, 'error': 'Login data and plan type are required'})
    
    if plan_type not in PLANS:
        return jsonify({'success': False, 'error': 'Invalid plan type'})
    
    # Read logins
    logins_data = read_json_file(LOGINS_FILE)
    
    # Check if login exists
    if plan_type not in logins_data or login_data not in logins_data[plan_type]:
        return jsonify({'success': False, 'error': 'Login not found'})
    
    # Remove login
    logins_data[plan_type].remove(login_data)
    write_json_file(LOGINS_FILE, logins_data)
    
    return jsonify({'success': True})

@app.route('/sales/toggle', methods=['POST'])
@login_required
def toggle_sales():
    current_status = sales_enabled()
    
    if current_status:
        suspend_sales()
        status = 'suspended'
    else:
        resume_sales()
        status = 'resumed'
    
    flash(f'Sales {status} successfully', 'success')
    return redirect(url_for('dashboard'))

@app.route('/coupons')
@login_required
def coupons():
    bot_config = read_json_file(BOT_CONFIG_FILE)
    coupons_data = bot_config.get('coupons', {})
    
    # Format data for display
    for code, coupon in coupons_data.items():
        if coupon['expiration_date']:
            coupon['expiration_formatted'] = datetime.fromisoformat(coupon['expiration_date']).strftime('%d/%m/%Y')
        else:
            coupon['expiration_formatted'] = 'Never'
            
        if coupon['discount_type'] == 'percentage':
            coupon['discount_formatted'] = f"{coupon['discount_value']}%"
        else:
            coupon['discount_formatted'] = format_currency(coupon['discount_value'])
            
        if coupon['min_purchase'] > 0:
            coupon['min_purchase_formatted'] = format_currency(coupon['min_purchase'])
        else:
            coupon['min_purchase_formatted'] = 'None'
            
        if coupon['max_uses'] == -1:
            coupon['uses_formatted'] = f"{coupon['uses']} / Unlimited"
        else:
            coupon['uses_formatted'] = f"{coupon['uses']} / {coupon['max_uses']}"
    
    return render_template('coupons.html', coupons=coupons_data, plans=PLANS)

@app.route('/coupons/add', methods=['POST'])
@login_required
def add_coupon_route():
    code = request.form.get('code')
    discount_type = request.form.get('discount_type')
    discount_value = request.form.get('discount_value')
    expiration_date = request.form.get('expiration_date')
    max_uses = request.form.get('max_uses')
    min_purchase = request.form.get('min_purchase')
    applicable_plans = request.form.getlist('applicable_plans')
    
    # Validate inputs
    if not code or not discount_type or not discount_value:
        flash('Code, discount type and value are required', 'danger')
        return redirect(url_for('coupons'))
    
    # Process data
    try:
        discount_value = float(discount_value)
        
        if max_uses == 'unlimited':
            max_uses = -1
        else:
            max_uses = int(max_uses)
            
        min_purchase = float(min_purchase) if min_purchase else 0
        
        if not expiration_date:
            expiration_date = None
        else:
            # Convert from DD/MM/YYYY to ISO format
            day, month, year = map(int, expiration_date.split('/'))
            expiration_date = datetime(year, month, day).isoformat()
            
        if 'all' in applicable_plans:
            applicable_plans = ['all']
    except Exception as e:
        flash(f'Invalid input data: {e}', 'danger')
        return redirect(url_for('coupons'))
    
    # Add coupon
    success, message = add_coupon(
        code, discount_type, discount_value, expiration_date,
        max_uses, min_purchase, applicable_plans
    )
    
    if success:
        flash('Coupon added successfully', 'success')
    else:
        flash(f'Error adding coupon: {message}', 'danger')
    
    return redirect(url_for('coupons'))

@app.route('/coupons/delete/<code>', methods=['POST'])
@login_required
def delete_coupon_route(code):
    success = delete_coupon(code)
    
    if success:
        flash('Coupon deleted successfully', 'success')
    else:
        flash('Error deleting coupon', 'danger')
    
    return redirect(url_for('coupons'))

# Payment Settings Routes
@app.route('/payment-settings')
@login_required
def payment_settings():
    """Payment settings page with PIX and Mercado Pago configuration"""
    try:
        # Get payment settings from bot_config
        bot_config = read_json_file(BOT_CONFIG_FILE)
        payment_settings = bot_config.get('payment_settings', {})
        
        # Get PIX settings
        pix_settings = payment_settings.get('pix', {
            'enabled': True,
            'key': 'nossaempresa@email.com',
            'name': 'Empresa UniTV LTDA',
            'bank': 'Banco UniTV'
        })
        
        # Get Mercado Pago settings
        mercado_pago_settings = payment_settings.get('mercado_pago', {
            'enabled': False,
            'access_token': '',
            'public_key': ''
        })
        
        return render_template('payment_settings.html', 
                              pix=pix_settings, 
                              mercado_pago=mercado_pago_settings,
                              message=request.args.get('message'),
                              message_type=request.args.get('message_type', 'info'))
    except Exception as e:
        log_exception(e)
        logger.error(f"Error loading payment settings: {e}")
        flash('Erro ao carregar configurações de pagamento.', 'danger')
        return redirect(url_for('dashboard'))

@app.route('/payment-settings/pix', methods=['POST'])
@login_required
def save_pix_settings():
    """Save PIX payment settings"""
    try:
        # Get current settings
        bot_config = read_json_file(BOT_CONFIG_FILE)
        payment_settings = bot_config.get('payment_settings', {})
        
        # Update PIX settings
        pix_settings = {
            'enabled': 'enabled' in request.form,
            'key': request.form.get('key', ''),
            'name': request.form.get('name', ''),
            'bank': request.form.get('bank', '')
        }
        
        # Update settings in config
        if 'payment_settings' not in bot_config:
            bot_config['payment_settings'] = {}
        
        bot_config['payment_settings']['pix'] = pix_settings
        
        # Save updated config
        write_json_file(BOT_CONFIG_FILE, bot_config)
        
        return redirect(url_for('payment_settings', 
                              message='Configurações PIX salvas com sucesso!',
                              message_type='success'))
    except Exception as e:
        log_exception(e)
        logger.error(f"Error saving PIX settings: {e}")
        return redirect(url_for('payment_settings', 
                              message='Erro ao salvar configurações PIX.',
                              message_type='danger'))

@app.route('/payment-settings/mercado-pago', methods=['POST'])
@login_required
def save_mercado_pago_settings():
    """Save Mercado Pago payment settings"""
    try:
        # Get current settings
        bot_config = read_json_file(BOT_CONFIG_FILE)
        payment_settings = bot_config.get('payment_settings', {})
        
        # Update Mercado Pago settings
        mp_settings = {
            'enabled': 'enabled' in request.form,
            'access_token': request.form.get('access_token', ''),
            'public_key': request.form.get('public_key', '')
        }
        
        # Update settings in config
        if 'payment_settings' not in bot_config:
            bot_config['payment_settings'] = {}
        
        bot_config['payment_settings']['mercado_pago'] = mp_settings
        
        # Save updated config
        write_json_file(BOT_CONFIG_FILE, bot_config)
        
        return redirect(url_for('payment_settings', 
                              message='Configurações Mercado Pago salvas com sucesso!',
                              message_type='success'))
    except Exception as e:
        log_exception(e)
        logger.error(f"Error saving Mercado Pago settings: {e}")
        return redirect(url_for('payment_settings', 
                              message='Erro ao salvar configurações Mercado Pago.',
                              message_type='danger'))

# Error handlers
@app.errorhandler(404)
def page_not_found(e):
    return render_template('index.html', error="Page not found"), 404

@app.errorhandler(500)
def internal_server_error(e):
    return render_template('index.html', error="Internal server error"), 500

# Initialize the app
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
