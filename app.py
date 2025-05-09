import os
import json
import logging
import secrets
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, abort
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from support import (
    get_all_active_tickets, get_ticket, add_message_to_ticket, 
    close_ticket, mark_ticket_messages_as_read
)
from config import (
    USERS_FILE, PAYMENTS_FILE, LOGINS_FILE, BOT_CONFIG_FILE, AUTH_FILE, SESSION_FILE,
    TICKETS_FILE, PLANS, ADMIN_ID, SESSION_EXPIRY_HOURS
)
from utils import (
    read_json_file, write_json_file, add_login, add_coupon, delete_coupon,
    resume_sales, suspend_sales, sales_enabled, format_currency, create_auth_token, verify_auth_token,
    is_admin_telegram_id, is_allowed_telegram_id, create_session, get_session, delete_session,
    generate_access_code, verify_access_code, list_active_access_codes, is_root_admin,
    get_active_seasonal_discounts, add_seasonal_discount, remove_seasonal_discount,
    create_giveaway, get_giveaway, get_giveaways_for_admin, draw_giveaway_winners, cancel_giveaway,
    remove_plan_from_user, assign_plan_to_user, ban_user, unban_user
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

# Expor as variáveis de configuração para os templates
app.jinja_env.globals['config'] = {
    'ADMIN_ID': ADMIN_ID
}

# Login required decorator
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Debug session info
        logger.debug(f"Session in login_required: {session}")
        
        # Check if user is logged in
        if 'logged_in' not in session:
            logger.warning(f"User not logged in, redirecting to login from {request.path}")
            flash('Por favor, faça login para acessar esta página.', 'warning')
            return redirect(url_for('login', next=request.url))
        
        # Verify session token if available
        if 'session_token' in session:
            session_data = get_session(session['session_token'])
            if not session_data:
                # Session expired or invalid, clear session and redirect to login
                logger.warning(f"Invalid session token: {session['session_token'][:8]}...")
                session.clear()
                flash('Sua sessão expirou. Por favor, faça login novamente.', 'warning')
                return redirect(url_for('login', next=request.url))
            
            # Check if the user still has permission
            telegram_id = session.get('telegram_id')
            if telegram_id and not is_allowed_telegram_id(telegram_id):
                # User no longer has permission
                logger.warning(f"User {telegram_id} no longer has permission")
                delete_session(session['session_token'])
                session.clear()
                flash('Você não tem mais permissão para acessar o painel administrativo.', 'danger')
                return redirect(url_for('login'))
                
            # Session is valid, continue
            logger.debug(f"Valid session for user {telegram_id}")
        else:
            # No session token found but logged_in is True (old session)
            logger.warning("No session token found but logged_in is True")
            session.clear()
            flash('Sessão inválida. Por favor, faça login novamente.', 'warning')
            return redirect(url_for('login', next=request.url))
            
        return f(*args, **kwargs)
    return decorated_function

# Decorator para verificar se o usuário é admin root
def root_admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Verificar se o usuário está logado e tem um telegram_id na sessão
        if 'logged_in' not in session or 'telegram_id' not in session:
            logger.warning(f"User not logged in or missing telegram_id in root_admin_required")
            flash('Por favor, faça login para acessar esta página.', 'warning')
            return redirect(url_for('login', next=request.url))
        
        # Verificar se o usuário é o admin root
        telegram_id = session.get('telegram_id')
        
        # Log detalhado para debug
        logger.debug(f"root_admin_required: Checking if user {telegram_id} is root admin")
        logger.debug(f"ADMIN_ID from environment: {ADMIN_ID} (type: {type(ADMIN_ID)})")
        
        # Verificação robusta comparando com ADMIN_ID
        is_root = is_root_admin(telegram_id)
        logger.debug(f"is_root_admin({telegram_id}) returned: {is_root}")
        
        if not is_root:
            # Verificação adicional e detalhada para debug
            str_telegram_id = str(telegram_id).strip() if telegram_id else "None"
            str_admin_id = str(ADMIN_ID).strip() if ADMIN_ID else "None"
            logger.warning(f"User {telegram_id} attempted to access root admin area but is not root admin")
            logger.warning(f"Comparison: '{str_telegram_id}' vs root admin '{str_admin_id}', equal: {str_telegram_id == str_admin_id}")
            
            # Mensagem informativa para o usuário
            flash('Apenas o administrador principal pode acessar esta página.', 'danger')
            return redirect(url_for('dashboard'))
        
        # Se chegou aqui, é o admin root
        logger.debug(f"Access granted: User {telegram_id} confirmed as root admin")
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
        
        # Count unread support tickets
        telegram_id = session.get('telegram_id')
        unread_tickets = 0
        active_tickets = get_all_active_tickets()
        
        for ticket_id, ticket in active_tickets.items():
            has_unread = False
            for message in ticket['messages']:
                if not message['read'] and message['from_type'] == 'user':
                    has_unread = True
                    break
            if has_unread:
                unread_tickets += 1
        
        stats = {
            'total_users': len(users),
            'active_users': active_users,
            'pending_payments': pending_payments,
            'available_logins': available_logins,
            'pending_approvals': pending_approvals,
            'waiting_for_login': waiting_for_login,
            'sales_status': sales_status,
            'active_coupons': active_coupons,
            'unread_tickets': unread_tickets
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
        
        # Obter descontos sazonais ativos
        seasonal_discounts = get_active_seasonal_discounts()
        
        return render_template('users.html', user=user, user_id=user_id, payments=user_payments,
                               seasonal_discounts=seasonal_discounts, plans=PLANS)
    except Exception as e:
        log_exception(e)
        flash('Erro ao carregar detalhes do usuário. Tente novamente.', 'danger')
        return redirect(url_for('users'))
        
@app.route('/users/<user_id>/assign-plan', methods=['POST'])
@login_required
def assign_plan(user_id):
    try:
        # Obter dados do formulário
        plan_type = request.form.get('plan_type')
        duration_days = request.form.get('duration_days')
        
        # Validar o tipo de plano
        if plan_type not in PLANS:
            flash('Tipo de plano inválido.', 'danger')
            return redirect(url_for('user_detail', user_id=user_id))
        
        # Converter duração para inteiro se fornecida
        if duration_days:
            try:
                duration_days = int(duration_days)
            except ValueError:
                flash('Duração do plano inválida.', 'danger')
                return redirect(url_for('user_detail', user_id=user_id))
        else:
            duration_days = None
        
        # Atribuir plano ao usuário
        success, plan_id = assign_plan_to_user(user_id, plan_type, duration_days)
        if success:
            flash(f'Plano atribuído com sucesso ao usuário (ID do plano: {plan_id}).', 'success')
        else:
            flash('Erro ao atribuir plano ao usuário.', 'danger')
        
        return redirect(url_for('user_detail', user_id=user_id))
    except Exception as e:
        log_exception(e)
        flash('Erro ao atribuir plano ao usuário. Tente novamente.', 'danger')
        return redirect(url_for('user_detail', user_id=user_id))
        
@app.route('/users/<user_id>/remove-plan', methods=['POST'])
@login_required
def remove_plan(user_id):
    try:
        # Obter ID do plano se fornecido
        plan_id = request.form.get('plan_id')
        
        # Remover plano do usuário
        if remove_plan_from_user(user_id, plan_id):
            if plan_id:
                flash(f'Plano (ID: {plan_id}) removido com sucesso do usuário.', 'success')
            else:
                flash('Todos os planos removidos com sucesso do usuário.', 'success')
        else:
            flash('Erro ao remover plano do usuário.', 'danger')
        
        return redirect(url_for('user_detail', user_id=user_id))
    except Exception as e:
        log_exception(e)
        flash('Erro ao remover plano do usuário. Tente novamente.', 'danger')
        return redirect(url_for('user_detail', user_id=user_id))
        
@app.route('/users/<user_id>/ban', methods=['POST'])
@login_required
def ban_user_route(user_id):
    try:
        # Obter motivo do banimento
        reason = request.form.get('ban_reason', '')
        
        # Banir usuário
        if ban_user(user_id, reason):
            flash('Usuário banido com sucesso.', 'success')
        else:
            flash('Erro ao banir usuário.', 'danger')
        
        return redirect(url_for('user_detail', user_id=user_id))
    except Exception as e:
        log_exception(e)
        flash('Erro ao banir usuário. Tente novamente.', 'danger')
        return redirect(url_for('user_detail', user_id=user_id))
        
@app.route('/users/<user_id>/unban', methods=['POST'])
@login_required
def unban_user_route(user_id):
    try:
        # Desbanir usuário
        if unban_user(user_id):
            flash('Usuário desbanido com sucesso.', 'success')
        else:
            flash('Erro ao desbanir usuário.', 'danger')
        
        return redirect(url_for('user_detail', user_id=user_id))
    except Exception as e:
        log_exception(e)
        flash('Erro ao desbanir usuário. Tente novamente.', 'danger')
        return redirect(url_for('user_detail', user_id=user_id))

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
            
        # Verificar se temos o novo campo max_uses_per_user (para compatibilidade)
        if 'max_uses_per_user' not in coupon:
            coupon['max_uses_per_user'] = 1  # Default para cupons antigos
    
    # Obter descontos sazonais ativos
    seasonal_discounts = get_active_seasonal_discounts()
    
    # Formatar dados dos descontos sazonais para exibição
    for discount_id, discount in seasonal_discounts.items():
        expiration_date = datetime.fromisoformat(discount['expiration_date'])
        discount['expiration_formatted'] = expiration_date.strftime('%d/%m/%Y')
        discount['days_left'] = (expiration_date - datetime.now()).days
        
        # Formatar lista de planos aplicáveis
        plan_names = []
        for plan_type in discount['applicable_plans']:
            if plan_type in PLANS:
                plan_names.append(PLANS[plan_type]['name'])
        
        discount['plans_formatted'] = ', '.join(plan_names) if plan_names else 'All Plans'
    
    return render_template('coupons.html', coupons=coupons_data, plans=PLANS, 
                          seasonal_discounts=seasonal_discounts)
                          
@app.route('/seasonal-discounts/add', methods=['POST'])
@login_required
def add_seasonal_discount_route():
    try:
        # Obter dados do formulário
        discount_percent = request.form.get('discount_percent')
        expiration_days = request.form.get('expiration_days')
        applicable_plans = request.form.getlist('applicable_plans')
        
        # Validar dados
        try:
            discount_percent = int(discount_percent)
            expiration_days = int(expiration_days)
        except (ValueError, TypeError):
            flash('Valores inválidos para desconto ou dias de expiração.', 'danger')
            return redirect(url_for('coupons'))
            
        if discount_percent <= 0 or discount_percent > 100:
            flash('Percentual de desconto deve estar entre 1 e 100.', 'danger')
            return redirect(url_for('coupons'))
            
        if expiration_days <= 0:
            flash('Dias de expiração deve ser um número positivo.', 'danger')
            return redirect(url_for('coupons'))
        
        # Validar planos aplicáveis
        valid_plans = applicable_plans if applicable_plans else None
        
        # Adicionar desconto sazonal
        discount_id = add_seasonal_discount(discount_percent, expiration_days, valid_plans)
        
        if discount_id:
            flash('Desconto sazonal adicionado com sucesso.', 'success')
        else:
            flash('Erro ao adicionar desconto sazonal.', 'danger')
        
        return redirect(url_for('coupons'))
    except Exception as e:
        log_exception(e)
        flash('Erro ao adicionar desconto sazonal. Tente novamente.', 'danger')
        return redirect(url_for('coupons'))
        
@app.route('/seasonal-discounts/remove/<discount_id>', methods=['POST'])
@login_required
def remove_seasonal_discount_route(discount_id):
    try:
        # Remover desconto sazonal
        if remove_seasonal_discount(discount_id):
            flash('Desconto sazonal removido com sucesso.', 'success')
        else:
            flash('Erro ao remover desconto sazonal.', 'danger')
        
        return redirect(url_for('coupons'))
    except Exception as e:
        log_exception(e)
        flash('Erro ao remover desconto sazonal. Tente novamente.', 'danger')
        return redirect(url_for('coupons'))

@app.route('/coupons/add', methods=['POST'])
@login_required
def add_coupon_route():
    code = request.form.get('code')
    discount_type = request.form.get('discount_type')
    discount_value = request.form.get('discount_value')
    expiration_date = request.form.get('expiration_date')
    max_uses = request.form.get('max_uses')
    max_uses_per_user = request.form.get('max_uses_per_user')
    min_purchase = request.form.get('min_purchase')
    applicable_plans = request.form.getlist('applicable_plans')
    
    # Validate inputs
    if not code or not discount_type or not discount_value:
        flash('Code, discount type and value are required', 'danger')
        return redirect(url_for('coupons'))
    
    # Process data
    try:
        discount_value = float(discount_value)
        
        # Processar valor máximo de usos totais
        if max_uses == 'unlimited':
            max_uses = -1
        else:
            max_uses = int(max_uses)
        
        # Processar valor máximo de usos por usuário
        if not max_uses_per_user or max_uses_per_user == 'unlimited':
            max_uses_per_user = -1
        else:
            max_uses_per_user = int(max_uses_per_user)
            
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
        max_uses, max_uses_per_user, min_purchase, applicable_plans
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
@root_admin_required
def payment_settings():
    """Payment settings page with PIX and Mercado Pago configuration - restricted to root admin only"""
    try:
        # Log debug information about the session
        logger.debug(f"Session in payment_settings: {session}")
        
        # Get payment settings from bot_config
        bot_config = read_json_file(BOT_CONFIG_FILE)
        payment_settings = bot_config.get('payment_settings', {})
        
        # Get PIX settings or set default values if they don't exist
        pix_settings = payment_settings.get('pix', {})
        if not pix_settings:
            pix_settings = {
                'enabled': True,
                'key': 'nossaempresa@email.com',
                'name': 'Empresa UniTV LTDA',
                'bank': 'Banco UniTV'
            }
        
        # Get Mercado Pago settings or set default values if they don't exist
        mercado_pago_settings = payment_settings.get('mercado_pago', {})
        if not mercado_pago_settings:
            mercado_pago_settings = {
                'enabled': False,
                'access_token': '',
                'public_key': ''
            }
        
        # Get data for stats (required by dashboard.html template)
        users = read_json_file(USERS_FILE) or {}
        payments = read_json_file(PAYMENTS_FILE) or {}
        logins = read_json_file(LOGINS_FILE) or {}
        
        # Import the support module to get unread tickets count
        from support import get_unread_ticket_count
        
        # Create stats object for the dashboard template
        stats = {
            'total_users': len(users),
            'active_users': sum(1 for user in users.values() if user.get('subscription_end') and 
                               datetime.fromisoformat(user.get('subscription_end')) > datetime.now()),
            'pending_payments': sum(1 for p in payments.values() if p.get('status') == 'pending'),
            'available_logins': {
                '30_days': len(logins.get('30_days', [])),
                '6_months': len(logins.get('6_months', [])),
                '1_year': len(logins.get('1_year', []))
            },
            'pending_approvals': sum(1 for p in payments.values() if p.get('status') == 'pending_approval'),
            'waiting_for_login': sum(1 for p in payments.values() if p.get('status') == 'approved' and not p.get('login_delivered')),
            'sales_status': sales_enabled(),
            'active_coupons': len(bot_config.get('coupons', {})),
            'unread_tickets': get_unread_ticket_count(session.get('telegram_id'), 'admin')
        }
        
        # Log debug information
        logger.debug(f"Payment settings loaded successfully: PIX: {pix_settings.get('enabled')}, MP: {mercado_pago_settings.get('enabled')}")
        
        # Use try/except for template rendering
        try:
            return render_template('payment_settings.html', 
                                pix=pix_settings, 
                                mercado_pago=mercado_pago_settings,
                                stats=stats,
                                message=request.args.get('message'),
                                message_type=request.args.get('message_type', 'info'))
        except Exception as template_error:
            log_exception(template_error)
            logger.error(f"Error rendering payment_settings template: {template_error}")
            flash('Erro ao renderizar a página de configurações de pagamento.', 'danger')
            return redirect(url_for('dashboard'))
    except Exception as e:
        log_exception(e)
        logger.error(f"Error loading payment settings: {e}")
        flash('Erro ao carregar configurações de pagamento.', 'danger')
        return redirect(url_for('dashboard'))

# Alternative payment settings route
@app.route('/payment-config')
@login_required
@root_admin_required
def payment_config():
    """Alternative route to payment settings - restricted to root admin only"""
    try:
        # Get payment settings from bot_config
        bot_config = read_json_file(BOT_CONFIG_FILE)
        payment_settings = bot_config.get('payment_settings', {})
        
        # Get PIX settings or set default values if they don't exist
        pix_settings = payment_settings.get('pix', {})
        if not pix_settings:
            pix_settings = {
                'enabled': True,
                'key': 'nossaempresa@email.com',
                'name': 'Empresa UniTV LTDA',
                'bank': 'Banco UniTV'
            }
        
        # Get Mercado Pago settings or set default values if they don't exist
        mercado_pago_settings = payment_settings.get('mercado_pago', {})
        if not mercado_pago_settings:
            mercado_pago_settings = {
                'enabled': False,
                'access_token': '',
                'public_key': ''
            }
        
        # Get data for stats (required by dashboard.html template)
        users = read_json_file(USERS_FILE) or {}
        payments = read_json_file(PAYMENTS_FILE) or {}
        logins = read_json_file(LOGINS_FILE) or {}
        
        # Import the support module to get unread tickets count
        from support import get_unread_ticket_count
        
        # Create stats object for the dashboard template
        stats = {
            'total_users': len(users),
            'active_users': sum(1 for user in users.values() if user.get('subscription_end') and 
                            datetime.fromisoformat(user.get('subscription_end')) > datetime.now()),
            'pending_payments': sum(1 for p in payments.values() if p.get('status') == 'pending'),
            'available_logins': {
                '30_days': len(logins.get('30_days', [])),
                '6_months': len(logins.get('6_months', [])),
                '1_year': len(logins.get('1_year', []))
            },
            'pending_approvals': sum(1 for p in payments.values() if p.get('status') == 'pending_approval'),
            'waiting_for_login': sum(1 for p in payments.values() if p.get('status') == 'approved' and not p.get('login_delivered')),
            'sales_status': sales_enabled(),
            'active_coupons': len(bot_config.get('coupons', {})),
            'unread_tickets': get_unread_ticket_count(session.get('telegram_id'), 'admin')
        }
        
        logger.debug(f"Alternative payment settings loaded successfully")
        
        return render_template('payment_settings.html', 
                            pix=pix_settings, 
                            mercado_pago=mercado_pago_settings,
                            stats=stats,
                            message=request.args.get('message'),
                            message_type=request.args.get('message_type', 'info'))
    except Exception as e:
        log_exception(e)
        logger.error(f"Error in alternative payment settings route: {e}")
        flash('Erro ao carregar configurações de pagamento (alternativa).', 'danger')
        return redirect(url_for('dashboard'))

@app.route('/payment-settings/pix', methods=['POST'])
@login_required
@root_admin_required
def save_pix_settings():
    """Save PIX payment settings - restricted to root admin only"""
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
@root_admin_required
def save_mercado_pago_settings():
    """Save Mercado Pago payment settings - restricted to root admin only"""
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

# Webhook para receber notificações do Mercado Pago
@app.route('/webhooks/mercadopago', methods=['POST'])
def mercadopago_webhook():
    """
    Webhook para processar notificações de pagamento do Mercado Pago.
    Esta rota recebe notificações quando um pagamento via PIX é concluído no Mercado Pago.
    """
    try:
        logger.info("Received Mercado Pago webhook")
        
        # Verificar se a notificação é válida
        data = request.get_json()
        logger.debug(f"Mercado Pago webhook data: {data}")
        
        if not data:
            logger.warning("Invalid webhook payload: no JSON data")
            return jsonify({"status": "error", "message": "Invalid payload"}), 400
        
        # Verificar o tipo de notificação
        if 'action' not in data or data['action'] != 'payment.updated':
            logger.info(f"Ignoring notification with action: {data.get('action', 'unknown')}")
            return jsonify({"status": "success", "message": "Notification received but not processed"}), 200
        
        # Obter o ID do pagamento do Mercado Pago
        mp_payment_id = data.get('data', {}).get('id')
        if not mp_payment_id:
            logger.warning("No payment ID in webhook data")
            return jsonify({"status": "error", "message": "Missing payment ID"}), 400
        
        # Obter as configurações do Mercado Pago
        bot_config = read_json_file(BOT_CONFIG_FILE)
        mp_settings = bot_config.get('payment_settings', {}).get('mercado_pago', {})
        access_token = mp_settings.get('access_token')
        
        if not access_token:
            logger.error("Mercado Pago access token not configured")
            return jsonify({"status": "error", "message": "Mercado Pago not configured"}), 500
        
        # Verificar o status do pagamento na API do Mercado Pago
        headers = {"Authorization": f"Bearer {access_token}"}
        mp_response = requests.get(f"https://api.mercadopago.com/v1/payments/{mp_payment_id}", headers=headers)
        
        if mp_response.status_code != 200:
            logger.error(f"Failed to get payment data from Mercado Pago: {mp_response.status_code}")
            return jsonify({"status": "error", "message": "Failed to verify payment"}), 500
        
        payment_data = mp_response.json()
        payment_status = payment_data.get('status')
        
        # Se o pagamento foi aprovado
        if payment_status == 'approved':
            # Encontrar o pagamento em nosso sistema que tem esse ID do Mercado Pago
            payments = read_json_file(PAYMENTS_FILE) or {}
            our_payment_id = None
            our_payment = None
            
            for pid, p in payments.items():
                if p.get('mp_payment_id') == str(mp_payment_id):
                    our_payment_id = pid
                    our_payment = p
                    break
            
            if not our_payment:
                logger.warning(f"No matching payment found for Mercado Pago payment {mp_payment_id}")
                return jsonify({"status": "error", "message": "Payment not found"}), 404
            
            # Atualizar o status do pagamento para aprovado
            update_payment(our_payment_id, {
                'status': 'approved',
                'approved_at': datetime.now().isoformat(),
                'mp_payment_data': payment_data
            })
            
            # Processar a entrega do login
            user_id = our_payment.get('user_id')
            plan_type = our_payment.get('plan_type')
            
            logger.info(f"Processing automatic login delivery for payment {our_payment_id}")
            
            # Verificar se há login disponível
            login = get_available_login(plan_type)
            
            if login:
                # Atribuir login ao usuário
                assigned_login = assign_login_to_user(user_id, plan_type, our_payment_id)
                
                if assigned_login:
                    # Notificar o usuário via Telegram
                    from bot import bot  # Importação local para evitar importação circular
                    
                    bot.send_message(
                        user_id,
                        f"🎉 *Seu login UniTV está pronto!* 🎉\n\n"
                        f"Login: `{assigned_login}`\n\n"
                        f"Seu plano expira em {PLANS[plan_type]['duration_days']} dias.\n"
                        f"Aproveite sua assinatura UniTV! 📺✨",
                        parse_mode="Markdown"
                    )
                    
                    # Registrar a entrega automática
                    logger.info(f"Login {assigned_login} automatically delivered to user {user_id}")
                    
                    # Se um cupom foi usado, marcar como usado
                    if our_payment.get('coupon_code'):
                        use_coupon(our_payment.get('coupon_code'), user_id)
                else:
                    logger.error(f"Failed to assign login for payment {our_payment_id}")
            else:
                # Sem login disponível
                logger.warning(f"No available login for plan {plan_type} after payment {our_payment_id}")
                
                # Notificar o usuário
                from bot import bot
                
                bot.send_message(
                    user_id,
                    f"✅ *Pagamento Aprovado!* ✅\n\n"
                    f"Seu pagamento para o plano {PLANS[plan_type]['name']} foi aprovado!\n\n"
                    f"Estamos preparando seu login e você o receberá automaticamente em breve.\n"
                    f"Obrigado pela paciência!",
                    parse_mode="Markdown"
                )
                
                # Notificar o administrador
                bot.send_message(
                    ADMIN_ID,
                    f"⚠️ *Pagamento Aprovado via Mercado Pago, mas Sem Login Disponível* ⚠️\n\n"
                    f"ID do Pagamento: {our_payment_id}\n"
                    f"Usuário: {user_id}\n"
                    f"Plano: {PLANS[plan_type]['name']}\n\n"
                    f"Por favor, adicione novos logins usando /addlogin e o login será enviado automaticamente ao usuário.",
                    parse_mode="Markdown"
                )
            
            return jsonify({"status": "success", "message": "Payment processed successfully"}), 200
        
        logger.info(f"Payment {mp_payment_id} status is {payment_status}, no action taken")
        return jsonify({"status": "success", "message": "Notification received"}), 200
    
    except Exception as e:
        log_exception(e)
        logger.error(f"Error processing Mercado Pago webhook: {e}")
        return jsonify({"status": "error", "message": "Internal server error"}), 500

# Custom Jinja filters
@app.template_filter('formatcurrency')
def format_currency_filter(value):
    if value is None:
        return "R$ 0,00"
    return format_currency(value)

@app.template_filter('formatdate')
def format_date_filter(date_str):
    if not date_str:
        return ""
    try:
        dt = datetime.fromisoformat(date_str)
        return dt.strftime('%d/%m/%Y %H:%M')
    except:
        return date_str
        
# Giveaway Routes
@app.route('/giveaways')
@login_required
def giveaways():
    """Página de gerenciamento de sorteios"""
    try:
        # Obter todos os sorteios para exibição no painel administrativo
        giveaways = get_giveaways_for_admin()
        
        # Get data for stats (required by layout.html template)
        users = read_json_file(USERS_FILE) or {}
        payments = read_json_file(PAYMENTS_FILE) or {}
        logins = read_json_file(LOGINS_FILE) or {}
        bot_config = read_json_file(BOT_CONFIG_FILE) or {}
        
        # Import the support module to get unread tickets count
        from support import get_unread_ticket_count
        
        # Create stats object for the template
        stats = {
            'total_users': len(users),
            'active_users': sum(1 for user in users.values() if user.get('subscription_end') and 
                              datetime.fromisoformat(user.get('subscription_end')) > datetime.now()),
            'pending_payments': sum(1 for p in payments.values() if p.get('status') == 'pending'),
            'available_logins': {
                '30_days': len(logins.get('30_days', [])),
                '6_months': len(logins.get('6_months', [])),
                '1_year': len(logins.get('1_year', []))
            },
            'pending_approvals': sum(1 for p in payments.values() if p.get('status') == 'pending_approval'),
            'waiting_for_login': sum(1 for p in payments.values() if p.get('status') == 'approved' and not p.get('login_delivered')),
            'sales_status': sales_enabled(),
            'active_coupons': len(bot_config.get('coupons', {})),
            'unread_tickets': get_unread_ticket_count(session.get('telegram_id'), 'admin')
        }
        
        return render_template('giveaways.html', 
                              giveaways=giveaways, 
                              plans=PLANS,
                              stats=stats,
                              message=request.args.get('message'),
                              message_type=request.args.get('message_type', 'info'))
    except Exception as e:
        log_exception(e)
        flash('Erro ao carregar a página de sorteios.', 'danger')
        return redirect(url_for('dashboard'))

@app.route('/giveaways/create', methods=['POST'])
@login_required
def create_giveaway_route():
    """Criar um novo sorteio"""
    try:
        # Obter dados do formulário
        plan_type = request.form.get('plan_type')
        winners_count = int(request.form.get('winners_count', 1))
        duration_hours = int(request.form.get('duration_hours', 24))
        max_participants = request.form.get('max_participants')
        description = request.form.get('description')
        
        # Validar dados
        if plan_type not in PLANS:
            flash('Tipo de plano inválido.', 'danger')
            return redirect(url_for('giveaways'))
        
        if winners_count < 1 or winners_count > 10:
            flash('Número de ganhadores deve estar entre 1 e 10.', 'danger')
            return redirect(url_for('giveaways'))
        
        if duration_hours < 1 or duration_hours > 168:
            flash('Duração do sorteio deve estar entre 1 e 168 horas.', 'danger')
            return redirect(url_for('giveaways'))
        
        # Converter max_participants para int se não estiver vazio
        if max_participants:
            try:
                max_participants = int(max_participants)
                if max_participants < 0:
                    max_participants = None
            except:
                max_participants = None
        else:
            max_participants = None
        
        # Criar sorteio
        admin_id = session.get('telegram_id')
        giveaway_id = create_giveaway(admin_id, plan_type, winners_count, duration_hours, max_participants, description)
        
        if giveaway_id:
            flash(f'Sorteio #{giveaway_id} criado com sucesso! Compartilhe o sorteio através do bot.', 'success')
        else:
            flash('Erro ao criar sorteio. Tente novamente.', 'danger')
        
        return redirect(url_for('giveaways'))
    except Exception as e:
        log_exception(e)
        flash('Erro ao criar sorteio. Tente novamente.', 'danger')
        return redirect(url_for('giveaways'))

@app.route('/giveaways/draw')
@login_required
def draw_giveaway_winners_route():
    """Sortear ganhadores de um sorteio"""
    try:
        giveaway_id = request.args.get('giveaway_id')
        if not giveaway_id:
            flash('ID do sorteio não fornecido.', 'danger')
            return redirect(url_for('giveaways'))
        
        # Realizar sorteio
        winners = draw_giveaway_winners(giveaway_id)
        
        if winners is None:
            flash('Não foi possível realizar o sorteio. Verifique se o sorteio existe e está no status correto.', 'danger')
        elif len(winners) == 0:
            flash('Não há participantes suficientes para realizar o sorteio.', 'warning')
        else:
            flash(f'Sorteio realizado com sucesso! {len(winners)} ganhador(es) selecionado(s).', 'success')
        
        return redirect(url_for('giveaways'))
    except Exception as e:
        log_exception(e)
        flash('Erro ao realizar sorteio. Tente novamente.', 'danger')
        return redirect(url_for('giveaways'))

@app.route('/giveaways/cancel', methods=['POST'])
@login_required
def cancel_giveaway_route():
    """Cancelar um sorteio"""
    try:
        giveaway_id = request.form.get('giveaway_id')
        if not giveaway_id:
            flash('ID do sorteio não fornecido.', 'danger')
            return redirect(url_for('giveaways'))
        
        # Cancelar sorteio
        admin_id = session.get('telegram_id')
        success = cancel_giveaway(giveaway_id, admin_id)
        
        if success:
            flash(f'Sorteio #{giveaway_id} cancelado com sucesso.', 'success')
        else:
            flash('Não foi possível cancelar o sorteio. Verifique se o sorteio existe e está ativo.', 'danger')
        
        return redirect(url_for('giveaways'))
    except Exception as e:
        log_exception(e)
        flash('Erro ao cancelar sorteio. Tente novamente.', 'danger')
        return redirect(url_for('giveaways'))

@app.route('/giveaways/details')
@login_required
def get_giveaway_details():
    """Obter detalhes de um sorteio para exibição em modal"""
    try:
        giveaway_id = request.args.get('giveaway_id')
        if not giveaway_id:
            return '<div class="alert alert-danger">ID do sorteio não fornecido.</div>'
        
        # Obter dados do sorteio
        giveaway = get_giveaway(giveaway_id)
        
        if not giveaway:
            return '<div class="alert alert-danger">Sorteio não encontrado.</div>'
        
        # Renderizar template com detalhes do sorteio
        return render_template('giveaway_details.html', giveaway=giveaway)
    except Exception as e:
        log_exception(e)
        return '<div class="alert alert-danger">Erro ao carregar detalhes do sorteio.</div>'

@app.route('/giveaways/winners')
@login_required
def get_giveaway_winners():
    """Obter detalhes dos ganhadores de um sorteio para exibição em modal"""
    try:
        giveaway_id = request.args.get('giveaway_id')
        if not giveaway_id:
            return '<div class="alert alert-danger">ID do sorteio não fornecido.</div>'
        
        # Obter dados do sorteio
        giveaway = get_giveaway(giveaway_id)
        
        if not giveaway:
            return '<div class="alert alert-danger">Sorteio não encontrado.</div>'
        
        # Renderizar template com detalhes dos ganhadores
        return render_template('giveaway_winners.html', giveaway=giveaway)
    except Exception as e:
        log_exception(e)
        return '<div class="alert alert-danger">Erro ao carregar detalhes dos ganhadores.</div>'

# Error handlers
@app.errorhandler(404)
def page_not_found(e):
    return render_template('index.html', error="Page not found"), 404

@app.errorhandler(500)
def internal_server_error(e):
    return render_template('index.html', error="Internal server error"), 500

# Support tickets dashboard
@app.route('/support')
@login_required
def support_dashboard():
    try:
        # Obter dados para estatísticas
        users = read_json_file(USERS_FILE) or {}
        payments = read_json_file(PAYMENTS_FILE) or {}
        logins = read_json_file(LOGINS_FILE) or {}
        bot_config = read_json_file(BOT_CONFIG_FILE) or {}
        
        # Contar usuários ativos
        active_users = 0
        for user_id, user_data in users.items():
            if user_data and user_data.get('has_active_plan'):
                active_users += 1
        
        # Logins disponíveis
        available_logins = {
            '30_days': len(logins.get('30_days', [])),
            '6_months': len(logins.get('6_months', [])),
            '1_year': len(logins.get('1_year', []))
        }
        
        # Contar pagamentos pendentes de aprovação
        pending_approvals = 0
        for payment_id, payment_data in payments.items():
            if payment_data and payment_data.get('status') == 'pending_approval':
                pending_approvals += 1
                
        # Contar usuários aguardando login
        waiting_for_login = 0
        for payment_id, payment_data in payments.items():
            if payment_data and payment_data.get('status') == 'approved' and not payment_data.get('login_delivered'):
                waiting_for_login += 1
        
        # Status de vendas
        sales_status = bot_config.get('sales_enabled', True)
        
        # Cupons
        coupons = bot_config.get('coupons', {})
        active_coupons = len(coupons) if coupons else 0
        
        # Contar tickets não lidos
        telegram_id = session.get('telegram_id')
        unread_tickets = 0
        
        # Obter tickets (ativos e fechados)
        from support import get_all_closed_tickets
        active_tickets = get_all_active_tickets()
        closed_tickets = get_all_closed_tickets()
        
        # Obter o parâmetro de filtro (todos, ativos ou fechados)
        filter_type = request.args.get('filter', 'all')
        
        # Contar tickets não lidos para stats
        if active_tickets:
            for ticket_id, ticket in active_tickets.items():
                has_unread = False
                if 'messages' in ticket:
                    for message in ticket['messages']:
                        if not message.get('read', False) and message.get('from_type') == 'user':
                            has_unread = True
                            break
                if has_unread:
                    unread_tickets += 1
        
        # Converter para lista e aplicar filtro
        tickets_list = []
        
        # Adicionar tickets ativos se solicitado
        if filter_type in ['all', 'active']:
            if active_tickets:
                active_list = [ticket for _, ticket in active_tickets.items()]
                for ticket in active_list:
                    ticket['display_status'] = 'active'
                    tickets_list.append(ticket)
                
        # Adicionar tickets fechados se solicitado
        if filter_type in ['all', 'closed']:
            if closed_tickets:
                closed_list = [ticket for _, ticket in closed_tickets.items()]
                for ticket in closed_list:
                    ticket['display_status'] = 'closed'
                    tickets_list.append(ticket)
                    
        # Log para debug
        logger.debug(f"Quantidade de tickets ativos: {len(active_tickets)}")
        logger.debug(f"Quantidade de tickets fechados: {len(closed_tickets)}")
        logger.debug(f"Total de tickets: {len(active_tickets) + len(closed_tickets)}")
                
        # Ordenar por data de atualização (mais recentes primeiro)
        tickets_list.sort(key=lambda x: x.get('updated_at', ''), reverse=True)
        
        # Construir objeto stats para o template
        stats = {
            'total_users': len(users),
            'active_users': active_users,
            'pending_payments': pending_approvals,  # Mesmo que pending_approvals
            'available_logins': available_logins,
            'pending_approvals': pending_approvals,
            'waiting_for_login': waiting_for_login,
            'sales_status': sales_status,
            'active_coupons': active_coupons,
            'unread_tickets': unread_tickets,
            'total_tickets': len(active_tickets) + len(closed_tickets),
            'active_ticket_count': len(active_tickets),
            'closed_ticket_count': len(closed_tickets),
            'current_filter': filter_type
        }
        
        return render_template('support.html', 
                               tickets=tickets_list, 
                               admin_id=telegram_id,
                               stats=stats,
                               filter_type=filter_type)  # Adicionando stats e filtro ao template
    except Exception as e:
        logger.error(f"Error loading support dashboard: {e}")
        flash('Erro ao carregar o painel de suporte. Tente novamente.', 'danger')
        return redirect(url_for('dashboard'))

# View ticket details
@app.route('/support/ticket/<ticket_id>')
@login_required
def view_ticket(ticket_id):
    try:
        # Obter o ticket
        ticket = get_ticket(ticket_id)
        
        if not ticket:
            flash('Ticket não encontrado.', 'warning')
            return redirect(url_for('support_dashboard'))
        
        # Marcar mensagens como lidas pelo admin
        telegram_id = session.get('telegram_id')
        mark_ticket_messages_as_read(ticket_id, 'admin')
        
        # Obter dados para estatísticas (necessário para o layout base)
        users = read_json_file(USERS_FILE) or {}
        payments = read_json_file(PAYMENTS_FILE) or {}
        logins = read_json_file(LOGINS_FILE) or {}
        bot_config = read_json_file(BOT_CONFIG_FILE) or {}
        
        # Contar usuários ativos
        active_users = 0
        for user_id, user_data in users.items():
            if user_data and user_data.get('has_active_plan'):
                active_users += 1
        
        # Logins disponíveis
        available_logins = {
            '30_days': len(logins.get('30_days', [])),
            '6_months': len(logins.get('6_months', [])),
            '1_year': len(logins.get('1_year', []))
        }
        
        # Contar pagamentos pendentes de aprovação
        pending_approvals = 0
        for payment_id, payment_data in payments.items():
            if payment_data and payment_data.get('status') == 'pending_approval':
                pending_approvals += 1
                
        # Contar usuários aguardando login
        waiting_for_login = 0
        for payment_id, payment_data in payments.items():
            if payment_data and payment_data.get('status') == 'approved' and not payment_data.get('login_delivered'):
                waiting_for_login += 1
        
        # Status de vendas
        sales_status = bot_config.get('sales_enabled', True)
        
        # Cupons
        coupons = bot_config.get('coupons', {})
        active_coupons = len(coupons) if coupons else 0
        
        # Contar tickets não lidos
        unread_tickets = 0
        active_tickets = get_all_active_tickets()
        
        for ticket_item_id, ticket_item in active_tickets.items():
            has_unread = False
            for message in ticket_item['messages']:
                if not message['read'] and message['from_type'] == 'user':
                    has_unread = True
                    break
            if has_unread:
                unread_tickets += 1
        
        # Construir objeto stats para o template
        stats = {
            'total_users': len(users),
            'active_users': active_users,
            'pending_payments': pending_approvals,
            'available_logins': available_logins,
            'pending_approvals': pending_approvals,
            'waiting_for_login': waiting_for_login,
            'sales_status': sales_status,
            'active_coupons': active_coupons,
            'unread_tickets': unread_tickets
        }
        
        return render_template('ticket_detail.html', 
                               ticket=ticket,
                               admin_id=telegram_id,
                               stats=stats)  # Adicionando stats ao template
    except Exception as e:
        logger.error(f"Error viewing ticket: {e}")
        flash('Erro ao visualizar o ticket. Tente novamente.', 'danger')
        return redirect(url_for('support_dashboard'))

# Reply to ticket
@app.route('/support/ticket/<ticket_id>/reply', methods=['POST'])
@login_required
def reply_to_ticket(ticket_id):
    try:
        # Obter a resposta e outras opções
        reply_text = request.form.get('reply_text')
        close_after_reply = request.form.get('close_after_reply') == '1'
        
        if not reply_text:
            flash('A resposta não pode estar vazia.', 'warning')
            return redirect(url_for('view_ticket', ticket_id=ticket_id))
        
        # Obter informações do ticket para enviar notificação
        ticket = get_ticket(ticket_id)
        if not ticket:
            flash('Ticket não encontrado.', 'danger')
            return redirect(url_for('support_dashboard'))
            
        # Adicionar a resposta ao ticket
        telegram_id = session.get('telegram_id')
        success = add_message_to_ticket(ticket_id, telegram_id, 'admin', reply_text)
        
        if success:
            # Notificar o usuário pelo Telegram
            try:
                # Importando a função do bot
                from bot import notify_user_about_ticket_reply
                
                # Notificar o usuário via Telegram
                user_id = ticket['user_id']
                
                # Enviar notificação com status do ticket após resposta
                ticket_status = 'closed' if close_after_reply else 'open'
                
                # Enviar notificação ao usuário com o status apropriado
                success_notification = notify_user_about_ticket_reply(
                    ticket_id=ticket_id, 
                    user_id=user_id, 
                    text=reply_text,
                    ticket_status=ticket_status
                )
                
                if success_notification:
                    logger.info(f"Usuário {user_id} notificado sobre resposta ao ticket {ticket_id}")
                    flash('Resposta enviada com sucesso e usuário notificado via Telegram.', 'success')
                else:
                    # A função já registra o erro internamente
                    flash('Resposta enviada com sucesso, mas pode ter ocorrido um problema ao notificar o usuário.', 'warning')
            except Exception as notification_error:
                logger.error(f"Erro ao notificar usuário via Telegram: {notification_error}")
                flash('Resposta enviada com sucesso, mas ocorreu um erro ao notificar o usuário via Telegram.', 'warning')
            
            # Fechar o ticket se a opção estiver marcada
            if close_after_reply:
                try:
                    close_success = close_ticket(ticket_id, 'admin')
                    if close_success:
                        flash('Ticket fechado com sucesso após resposta.', 'success')
                    else:
                        flash('Resposta enviada, mas ocorreu um erro ao fechar o ticket.', 'warning')
                except Exception as close_error:
                    logger.error(f"Erro ao fechar ticket após resposta: {close_error}")
                    flash('Resposta enviada, mas ocorreu um erro ao fechar o ticket.', 'warning')
        else:
            flash('Erro ao enviar resposta. Tente novamente.', 'danger')
        
        # Redirecionar de acordo com o estado do ticket
        if close_after_reply:
            return redirect(url_for('support_dashboard'))
        else:
            return redirect(url_for('view_ticket', ticket_id=ticket_id))
    except Exception as e:
        logger.error(f"Error replying to ticket: {e}")
        flash('Erro ao responder ao ticket. Tente novamente.', 'danger')
        return redirect(url_for('view_ticket', ticket_id=ticket_id))

# Close ticket
@app.route('/support/ticket/<ticket_id>/close', methods=['POST'])
@login_required
def close_support_ticket(ticket_id):
    try:
        # Obter informações do ticket antes de fechá-lo
        ticket = get_ticket(ticket_id)
        if not ticket:
            flash('Ticket não encontrado.', 'danger')
            return redirect(url_for('support_dashboard'))
            
        # Fechar o ticket
        telegram_id = session.get('telegram_id')
        success = close_ticket(ticket_id, 'admin')
        
        if success:
            flash('Ticket fechado com sucesso.', 'success')
            
            # Notificar o usuário sobre o fechamento do ticket
            try:
                # Importar função para notificar o usuário
                from bot import notify_user_about_ticket_reply
                
                # Preparar mensagem de fechamento
                user_id = ticket['user_id']
                close_message = (
                    "Este ticket foi fechado por um administrador.\n\n"
                    "Se você tiver outras dúvidas ou precisar de assistência adicional, "
                    "você pode abrir um novo ticket a qualquer momento através do menu de suporte."
                )
                
                # Enviar notificação ao usuário com status closed
                notify_user_about_ticket_reply(
                    ticket_id=ticket_id,
                    user_id=user_id,
                    text=close_message,
                    ticket_status='closed'
                )
                
                logger.info(f"Usuário {user_id} notificado sobre fechamento do ticket {ticket_id}")
            except Exception as notification_error:
                logger.error(f"Erro ao notificar usuário sobre fechamento do ticket: {notification_error}")
                # Não retornamos erro ao admin, pois o ticket foi fechado com sucesso
        else:
            flash('Erro ao fechar o ticket. Tente novamente.', 'danger')
        
        return redirect(url_for('support_dashboard'))
    except Exception as e:
        logger.error(f"Error closing ticket: {e}")
        flash('Erro ao fechar o ticket. Tente novamente.', 'danger')
        return redirect(url_for('view_ticket', ticket_id=ticket_id))

# Reopen ticket
@app.route('/support/ticket/<ticket_id>/reopen', methods=['POST'])
@login_required
def reopen_ticket(ticket_id):
    try:
        # Obter informações do ticket antes de reabri-lo
        ticket = get_ticket(ticket_id)
        if not ticket:
            flash('Ticket não encontrado.', 'danger')
            return redirect(url_for('support_dashboard'))
            
        # Armazenar o ID do usuário antes de reabrir (para notificação)
        user_id = ticket['user_id']
        
        # Reabrir o ticket
        from support import reopen_ticket as support_reopen_ticket
        success = support_reopen_ticket(ticket_id)
        
        if success:
            flash('Ticket reaberto com sucesso.', 'success')
            
            # Notificar o usuário sobre a reabertura do ticket
            try:
                # Importar função para notificar o usuário
                from bot import notify_user_about_ticket_reply
                
                # Preparar mensagem de reabertura
                reopen_message = (
                    "Este ticket foi reaberto por um administrador.\n\n"
                    "Nossa equipe de suporte continuará a atender sua solicitação. "
                    "Você receberá uma notificação quando houver uma nova resposta."
                )
                
                # Enviar notificação ao usuário com status open
                notify_user_about_ticket_reply(
                    ticket_id=ticket_id,
                    user_id=user_id,
                    text=reopen_message,
                    ticket_status='open'
                )
                
                logger.info(f"Usuário {user_id} notificado sobre reabertura do ticket {ticket_id}")
            except Exception as notification_error:
                logger.error(f"Erro ao notificar usuário sobre reabertura do ticket: {notification_error}")
                # Não retornamos erro ao admin, pois o ticket foi reaberto com sucesso
        else:
            flash('Erro ao reabrir o ticket. Tente novamente.', 'danger')
        
        return redirect(url_for('view_ticket', ticket_id=ticket_id))
    except Exception as e:
        logger.error(f"Error reopening ticket: {e}")
        flash('Erro ao reabrir o ticket. Tente novamente.', 'danger')
        return redirect(url_for('view_ticket', ticket_id=ticket_id))

# Initialize the app
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
