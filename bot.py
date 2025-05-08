import os
import time
import telebot
from telebot import types
import threading
import logging
import json
from datetime import datetime, timedelta
import uuid

# Import from our modules
from config import (
    BOT_TOKEN, ADMIN_ID, PLANS, USERS_FILE, PAYMENTS_FILE,
    LOGINS_FILE, BOT_CONFIG_FILE, AUTH_FILE, GIVEAWAYS_FILE
)
from utils import (
    get_user, create_user, save_user, create_payment, update_payment,
    get_payment, cancel_payment, _cancel_mercado_pago_payment, get_pending_approvals, 
    get_users_waiting_for_login, check_should_suspend_sales, suspend_sales, 
    resume_sales, sales_enabled, format_currency, calculate_plan_price, 
    get_available_login, add_login, assign_login_to_user, get_user_pending_payment, 
    add_coupon, validate_coupon, use_coupon, delete_coupon, apply_referral_discount, 
    process_successful_referral, get_expiring_subscriptions, read_json_file, write_json_file,
    create_auth_token, is_admin_telegram_id, is_allowed_telegram_id,
    add_allowed_telegram_id, remove_allowed_telegram_id, generate_access_code,
    get_giveaway, get_giveaways_for_admin, create_giveaway, draw_giveaway_winners,
    cancel_giveaway, add_participant_to_giveaway, get_active_giveaways, 
    redraw_giveaway, confirm_giveaway_win, check_expired_confirmations,
    notify_users_about_giveaway
)

# Função para resolver pagamentos fantasmas
def fix_inconsistent_payments():
    """
    Identifica e corrige pagamentos inconsistentes no sistema.
    - Marca pagamentos fantasma como entregues
    - Inicializa a estrutura de planos para usuários que não a possuem
    
    Returns:
        int: Número de pagamentos corrigidos
    """
    payments = read_json_file(PAYMENTS_FILE)
    users = read_json_file(USERS_FILE)
    
    # Contador de correções
    fixed_count = 0
    
    # 1. Identificar pagamentos aprovados mas não entregues
    for payment_id, payment in payments.items():
        if payment.get('status') == 'approved' and not payment.get('login_delivered', False):
            user_id = payment.get('user_id')
            plan_type = payment.get('plan_type')
            
            if not user_id or not plan_type:
                logger.warning(f"Pagamento ID {payment_id} com dados incompletos - ignorando")
                # Marcar como entregue para evitar notificações falsas
                payment['login_delivered'] = True
                payment['is_ghost_payment'] = True
                fixed_count += 1
                continue
                
            user = users.get(str(user_id))
            if not user:
                logger.warning(f"Usuário ID {user_id} não encontrado para pagamento ID {payment_id}")
                # Marcar como entregue para evitar notificações falsas
                payment['login_delivered'] = True
                payment['is_ghost_payment'] = True
                fixed_count += 1
                continue
            
            # 2. Verificar se o usuário tem a estrutura de planos
            if 'plans' not in user:
                logger.info(f"Inicializando estrutura de planos para usuário ID {user_id}")
                user['plans'] = []
                fixed_count += 1
            
            # 3. Verificar se o pagamento é muito antigo (mais de 60 dias)
            if payment.get('created_at'):
                try:
                    payment_date = datetime.fromisoformat(payment.get('created_at'))
                    cutoff_date = datetime.now() - timedelta(days=60)
                    if payment_date < cutoff_date:
                        logger.info(f"Pagamento ID {payment_id} é muito antigo ({payment_date.isoformat()}). Marcando como entregue.")
                        payment['login_delivered'] = True
                        payment['is_ghost_payment'] = True
                        fixed_count += 1
                        continue
                except (ValueError, TypeError):
                    pass
            
    # 4. Salvar as alterações
    if fixed_count > 0:
        logger.info(f"Corrigido(s) {fixed_count} pagamento(s) inconsistente(s)")
        write_json_file(PAYMENTS_FILE, payments)
        write_json_file(USERS_FILE, users)
    
    return fixed_count

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Initialize bot
bot = telebot.TeleBot(BOT_TOKEN)

# Background tasks
def check_login_availability():
    """Check if logins are available, notify admin if they're running low, and check for expired payments"""
    while True:
        try:
            logins = read_json_file(LOGINS_FILE)
            bot_config = read_json_file(BOT_CONFIG_FILE)
            
            # Calculate total logins
            total_logins = sum(len(logins[plan_type]) for plan_type in logins)
            
            # If no logins available and sales are still enabled
            if total_logins == 0 and bot_config.get('sales_enabled', True):
                # Check if warning was already sent
                if not bot_config.get('warning_sent', False):
                    bot.send_message(
                        ADMIN_ID, 
                        "⚠️ *ALERTA IMPORTANTE* ⚠️\n\n"
                        "Não há mais logins disponíveis! As vendas serão suspensas automaticamente "
                        "em 5 minutos se nenhum login for adicionado.\n\n"
                        "Use /addlogin para adicionar novos logins.",
                        parse_mode="Markdown"
                    )
                    
                    # Update warning sent flag
                    bot_config['warning_sent'] = True
                    bot_config['sales_suspended_time'] = (datetime.now() + timedelta(minutes=5)).isoformat()
                    write_json_file(BOT_CONFIG_FILE, bot_config)
                
                # Check if the suspension time has passed
                elif bot_config.get('sales_suspended_time'):
                    suspension_time = datetime.fromisoformat(bot_config['sales_suspended_time'])
                    if datetime.now() >= suspension_time:
                        suspend_sales()
                        bot.send_message(
                            ADMIN_ID,
                            "🛑 *VENDAS SUSPENSAS* 🛑\n\n"
                            "As vendas foram suspensas automaticamente porque não há logins disponíveis.\n\n"
                            "Use /addlogin para adicionar novos logins e /resumesales para retomar as vendas.",
                            parse_mode="Markdown"
                        )
            
            # Check for pending users waiting for logins
            waiting_users = get_users_waiting_for_login()
            if waiting_users:
                # Check if there are logins for these users
                for payment in waiting_users:
                    plan_type = payment['plan_type']
                    user_id = payment['user_id']
                    payment_id = payment['payment_id']
                    
                    login = get_available_login(plan_type)
                    if login:
                        # Assign login to user
                        assigned_login = assign_login_to_user(user_id, plan_type, payment_id)
                        
                        if assigned_login:
                            bot.send_message(
                                user_id,
                                f"🎉 *Seu login UniTV está pronto!* 🎉\n\n"
                                f"Login: `{assigned_login}`\n\n"
                                f"Seu plano expira em {PLANS[plan_type]['duration_days']} dias.\n"
                                f"Aproveite sua assinatura UniTV! 📺✨",
                                parse_mode="Markdown"
                            )
                            
                            bot.send_message(
                                ADMIN_ID,
                                f"✅ Login enviado automaticamente para o usuário ID: {user_id}\n"
                                f"Plano: {PLANS[plan_type]['name']}"
                            )
                    else:
                        # Notify admin about missing logins
                        bot.send_message(
                            ADMIN_ID,
                            f"⚠️ *USUÁRIO AGUARDANDO LOGIN* ⚠️\n\n"
                            f"Um usuário (ID: {user_id}) pagou pelo plano {PLANS[plan_type]['name']} "
                            f"mas não há logins disponíveis para este plano.\n\n"
                            f"Use /addlogin para adicionar novos logins.",
                            parse_mode="Markdown"
                        )
            
            # Check for expiring subscriptions
            expiring_subs = get_expiring_subscriptions(days_threshold=3)
            for sub in expiring_subs:
                user_id = sub['user_id']
                days_left = sub['days_left']
                plan_type = sub['plan_type']
                plan_id = sub.get('plan_id')  # pode ser None para planos antigos
                
                # Enviar notificação individualizada para cada plano
                bot.send_message(
                    user_id,
                    f"⏰ *Seu plano UniTV está prestes a expirar!* ⏰\n\n"
                    f"Seu plano {PLANS[plan_type]['name']} expira em {days_left} dias.\n\n"
                    f"Para renovar sua assinatura, use o comando /start e escolha seu novo plano.",
                    parse_mode="Markdown"
                )
                
                # Marcar este plano específico como notificado
                mark_expiration_notified(user_id, plan_id)
            
            # Check for pending payment approvals
            pending_approvals = get_pending_approvals()
            if pending_approvals and not bot_config.get('pending_payment_notified'):
                bot.send_message(
                    ADMIN_ID,
                    f"💰 *Pagamentos Pendentes* 💰\n\n"
                    f"Você tem {len(pending_approvals)} pagamentos aguardando aprovação.\n"
                    f"Use /payments para ver os detalhes.",
                    parse_mode="Markdown"
                )
                bot_config['pending_payment_notified'] = True
                write_json_file(BOT_CONFIG_FILE, bot_config)
            
            # ======= Verificar pagamentos PIX expirados do Mercado Pago =======
            # Verificar pagamentos pendentes no sistema e cancelar os expirados (mais de 10 minutos)
            payments = read_json_file(PAYMENTS_FILE)
            current_time = datetime.now()
            payments_updated = False
            
            for payment_id, payment in payments.items():
                if payment['status'] == 'pending' and payment.get('mp_payment_id'):
                    # Verificar se o pagamento já passou do tempo limite (10 minutos)
                    if 'created_at' in payment:
                        created_at = datetime.fromisoformat(payment['created_at'])
                        expiration_time = created_at + timedelta(minutes=10)
                        
                        if current_time > expiration_time:
                            logger.info(f"Pagamento expirado encontrado: {payment_id}, Mercado Pago ID: {payment.get('mp_payment_id')}")
                            
                            # Cancelar o pagamento no Mercado Pago
                            if _cancel_mercado_pago_payment(payment.get('mp_payment_id')):
                                logger.info(f"Pagamento Mercado Pago {payment.get('mp_payment_id')} cancelado por tempo expirado")
                            
                            # Atualizar status para expirado
                            payment['status'] = 'expired'
                            payments[payment_id] = payment
                            payments_updated = True
                            
                            # Notificar o usuário
                            try:
                                user_id = payment['user_id']
                                bot.send_message(
                                    user_id,
                                    f"⏰ *Pagamento PIX Expirado* ⏰\n\n"
                                    f"O QR Code PIX para seu pagamento expirou após 10 minutos.\n"
                                    f"Para tentar novamente, inicie um novo pagamento usando o comando /start.",
                                    parse_mode="Markdown"
                                )
                            except Exception as e:
                                logger.error(f"Erro ao notificar usuário sobre pagamento expirado: {e}")
            
            # Salvar pagamentos atualizados, se necessário
            if payments_updated:
                write_json_file(PAYMENTS_FILE, payments)
        
        except Exception as e:
            logger.error(f"Error in background task: {e}")
        
        # Run every 5 minutes
        time.sleep(300)

# Check giveaways tasks
def check_giveaways():
    """Check for expired giveaway confirmations and redraws, and send periodic notifications"""
    # Contador para notificações periódicas (25 minutos = 25 * 60 segundos)
    notification_counter = 0
    
    while True:
        try:
            # Verificar confirmações expiradas
            redraws_needed = check_expired_confirmations()
            
            # Notificar novos ganhadores, se houver
            for giveaway_id, info in redraws_needed.items():
                giveaway = info.get('giveaway')
                expired_winners = info.get('expired_winners', [])
                
                if not giveaway:
                    continue
                
                # Realizar novo sorteio
                new_winners = redraw_giveaway(giveaway_id, len(expired_winners))
                
                if not new_winners:
                    continue
                
                # Notificar novos ganhadores
                for winner_id in new_winners:
                    try:
                        # Enviar mensagem para o ganhador
                        keyboard = types.InlineKeyboardMarkup()
                        keyboard.add(
                            types.InlineKeyboardButton(
                                "✅ Confirmar Participação",
                                callback_data=f"confirm_giveaway_{giveaway_id}"
                            )
                        )
                        
                        bot.send_message(
                            winner_id,
                            f"🎉 *PARABÉNS! Você foi sorteado!* 🎉\n\n"
                            f"Você ganhou o seguinte plano no sorteio:\n"
                            f"*{giveaway['plan_name']}*\n\n"
                            f"⚠️ *ATENÇÃO*: Você tem 10 minutos para confirmar sua participação clicando no botão abaixo.\n"
                            f"Caso contrário, um novo ganhador será sorteado.",
                            parse_mode="Markdown",
                            reply_markup=keyboard
                        )
                        
                        # Notificar admin
                        bot.send_message(
                            ADMIN_ID,
                            f"🔄 *NOVO SORTEIO REALIZADO* 🔄\n\n"
                            f"Sorteio #{giveaway_id}\n"
                            f"Plano: {giveaway['plan_name']}\n"
                            f"Novo ganhador: {winner_id}\n"
                            f"(Substituindo ganhador que não confirmou)",
                            parse_mode="Markdown"
                        )
                    except Exception as e:
                        logger.error(f"Erro ao notificar novo ganhador {winner_id}: {e}")
            
            # Enviar notificações periódicas sobre sorteios ativos (a cada 25 minutos)
            notification_counter += 1
            
            # Se passaram 25 minutos (25 iterações de 1 minuto cada)
            if notification_counter >= 25:
                # Resetar o contador
                notification_counter = 0
                
                # Obter sorteios ativos
                active_giveaways = get_active_giveaways()
                
                if active_giveaways:
                    logger.info(f"Enviando notificação periódica sobre {len(active_giveaways)} sorteios ativos")
                    
                    # Obter todos os usuários
                    users = read_json_file(USERS_FILE)
                    
                    if users:
                        # Preparar mensagem sobre os sorteios
                        giveaway_message = "🎁 *SORTEIOS ATIVOS* 🎁\n\n"
                        giveaway_message += "Temos sorteios ativos que você pode participar!\n"
                        giveaway_message += "Use o comando /start e clique no botão 'Sorteios Ativos' para participar.\n\n"
                        giveaway_message += "Sorteios disponíveis:\n"
                        
                        # Adicionar informações sobre cada sorteio
                        for giveaway_id, giveaway in active_giveaways.items():
                            if giveaway.get('status') == 'active':
                                plan_name = giveaway.get('plan_name', 'Desconhecido')
                                end_date = datetime.fromisoformat(giveaway["ends_at"])
                                remaining_time = end_date - datetime.now()
                                remaining_hours = int(remaining_time.total_seconds() / 3600)
                                remaining_minutes = int((remaining_time.total_seconds() % 3600) / 60)
                                
                                # Adicionar informações do sorteio à mensagem
                                giveaway_message += f"- *{plan_name}* (Encerra em {remaining_hours}h {remaining_minutes}min)\n"
                        
                        # Enviar mensagem para todos os usuários
                        sent_count = 0
                        for user_id in users:
                            try:
                                # Verificar se o usuário já está participando de todos os sorteios
                                all_participating = True
                                for giveaway_id, giveaway in active_giveaways.items():
                                    if giveaway.get('status') == 'active' and str(user_id) not in giveaway.get('participants', []):
                                        all_participating = False
                                        break
                                
                                # Só enviar notificação se o usuário não estiver participando de todos os sorteios
                                if not all_participating:
                                    bot.send_message(
                                        user_id,
                                        giveaway_message,
                                        parse_mode="Markdown"
                                    )
                                    sent_count += 1
                            except Exception as e:
                                logger.error(f"Erro ao enviar notificação periódica para o usuário {user_id}: {e}")
                        
                        logger.info(f"Notificação de sorteio enviada para {sent_count} usuários")
                
        except Exception as e:
            logger.error(f"Error in giveaway background task: {e}")
        
        # Run every 1 minute
        time.sleep(60)


# Start background tasks
def start_background_tasks():
    # Thread para verificar disponibilidade de logins
    login_thread = threading.Thread(target=check_login_availability)
    login_thread.daemon = True
    login_thread.start()
    
    # Thread para verificar sorteios
    giveaway_thread = threading.Thread(target=check_giveaways)
    giveaway_thread.daemon = True
    giveaway_thread.start()

# Start command
@bot.message_handler(commands=['start'])
def start_command(message):
    user_id = message.from_user.id
    user = get_user(user_id)
    
    # Check if referred
    args = message.text.split()
    referrer_id = None
    if len(args) > 1 and args[1].isdigit():
        referrer_id = args[1]
    
    # Create user if not exists
    if not user:
        user = create_user(
            user_id,
            message.from_user.username,
            message.from_user.first_name,
            message.from_user.last_name,
            referrer_id
        )
        
        # Notify referrer if exists
        if referrer_id and referrer_id != str(user_id):
            referrer = get_user(referrer_id)
            if referrer:
                # Update referrer's referrals list
                if 'referrals' not in referrer:
                    referrer['referrals'] = []
                
                referrer['referrals'].append(str(user_id))
                save_user(referrer_id, referrer)
                
                # Notify referrer
                bot.send_message(
                    referrer_id,
                    f"🎉 Você tem um novo indicado! {message.from_user.first_name} se registrou usando seu link de indicação.\n\n"
                    f"Quando ele fizer a primeira compra, você ganhará um desconto em sua próxima renovação!",
                )
    
    # Create welcome message
    welcome_msg = (
        f"👋 Olá {message.from_user.first_name}! Bem-vindo à loja da UniTV! 📺✨\n\n"
        f"Escolha uma das opções abaixo para continuar:"
    )
    
    # Create keyboard
    keyboard = types.InlineKeyboardMarkup(row_width=1)
    
    # Add buttons based on user status
    if user.get('has_active_plan'):
        # Obter todos os planos ativos do usuário
        active_plans = get_user_plans(user_id)
        
        # Verificar se algum plano está próximo de expirar (menos de 10 dias)
        renew_button_needed = False
        
        if active_plans:
            for plan in active_plans:
                expiration_date = datetime.fromisoformat(plan.get('expiration_date'))
                days_left = (expiration_date - datetime.now()).days
                if days_left <= 10:
                    renew_button_needed = True
                    break
        
        # Add account info button
        keyboard.add(
            types.InlineKeyboardButton("📊 Minha Conta", callback_data="my_account")
        )
        
        # Sempre mostrar botão para adquirir novo plano/login
        keyboard.add(
            types.InlineKeyboardButton("➕ Adquirir Novo Plano", callback_data="show_plans")
        )
        
        # Add renew button if any plan is expiring soon
        if renew_button_needed:
            keyboard.add(
                types.InlineKeyboardButton("🔄 Renovar Assinatura", callback_data="show_plans")
            )
    else:
        # Check if sales are enabled
        if sales_enabled():
            keyboard.add(
                types.InlineKeyboardButton("🛒 Ver Planos", callback_data="show_plans")
            )
        else:
            welcome_msg += "\n\n⚠️ *As vendas estão temporariamente suspensas devido à alta demanda.* ⚠️"
    
    # Adicionar botão de sorteios ativos para todos os usuários
    active_giveaways = get_active_giveaways()
    if active_giveaways:
        keyboard.add(
            types.InlineKeyboardButton("🎁 Sorteios Ativos", callback_data="view_active_giveaways")
        )
    
    # Add support button
    keyboard.add(
        types.InlineKeyboardButton("💬 Suporte", callback_data="support"),
        types.InlineKeyboardButton("🔗 Programa de Indicação", callback_data="referral_program")
    )
    
    # Add giveaway button for admins
    if is_admin_telegram_id(str(user_id)):
        keyboard.add(
            types.InlineKeyboardButton("🎰 Gerenciar Sorteios", callback_data="admin_giveaways")
        )
    
    # Send the message
    bot.send_message(
        message.chat.id,
        welcome_msg,
        reply_markup=keyboard,
        parse_mode="Markdown"
    )

# Account info
@bot.callback_query_handler(func=lambda call: call.data == "my_account")
def my_account(call):
    user_id = call.from_user.id
    user = get_user(user_id)
    
    if not user or not user.get('has_active_plan'):
        bot.answer_callback_query(call.id, "Você não possui um plano ativo.")
        start_command(call.message)
        return
    
    # Obter todos os planos ativos do usuário
    active_plans = get_user_plans(user_id)
    
    if not active_plans:
        bot.answer_callback_query(call.id, "Você não possui um plano ativo.")
        start_command(call.message)
        return
    
    account_msg = f"📊 *Informações da Conta* 📊\n\n"
    
    # Mostrar informações de cada plano ativo
    if len(active_plans) == 1:
        # Se tiver apenas um plano, mostrar no formato tradicional
        plan = active_plans[0]
        plan_type = plan.get('plan_type')
        expiration_date = datetime.fromisoformat(plan.get('expiration_date'))
        days_left = max(0, (expiration_date - datetime.now()).days)
        
        account_msg += (
            f"*Plano Atual:* {PLANS[plan_type]['name']}\n"
            f"*Dias Restantes:* {days_left}\n"
            f"*Expira em:* {expiration_date.strftime('%d/%m/%Y')}\n\n"
            f"*Login:* `{plan.get('login_info')}`\n\n"
        )
    else:
        # Se tiver múltiplos planos, mostrar uma lista
        account_msg += f"*Você possui {len(active_plans)} planos ativos:*\n\n"
        
        for i, plan in enumerate(active_plans):
            plan_type = plan.get('plan_type')
            expiration_date = datetime.fromisoformat(plan.get('expiration_date'))
            days_left = max(0, (expiration_date - datetime.now()).days)
            
            account_msg += (
                f"*Plano {i+1}:* {PLANS[plan_type]['name']}\n"
                f"*Dias Restantes:* {days_left}\n"
                f"*Expira em:* {expiration_date.strftime('%d/%m/%Y')}\n"
                f"*Login:* `{plan.get('login_info')}`\n\n"
            )
    
    # Add referral information
    account_msg += (
        f"🔗 *Programa de Indicação* 🔗\n"
        f"Pessoas indicadas: {len(user.get('referrals', []))}\n"
        f"Indicações bem-sucedidas: {user.get('successful_referrals', 0)}\n\n"
    )
    
    # Create keyboard
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        types.InlineKeyboardButton("🔙 Voltar", callback_data="start"),
        types.InlineKeyboardButton("🔄 Adquirir Novo Plano", callback_data="show_plans"),
        types.InlineKeyboardButton("💬 Suporte", callback_data="support")
    )
    
    bot.edit_message_text(
        account_msg,
        call.message.chat.id,
        call.message.message_id,
        reply_markup=keyboard,
        parse_mode="Markdown"
    )

# Show plans
@bot.callback_query_handler(func=lambda call: call.data == "show_plans")
def show_plans(call):
    user_id = call.from_user.id
    user = get_user(user_id)
    
    # Check if sales are enabled
    if not sales_enabled():
        bot.answer_callback_query(call.id, "Vendas temporariamente suspensas devido à alta demanda.")
        bot.edit_message_text(
            "⚠️ *Vendas Suspensas* ⚠️\n\n"
            "As vendas estão temporariamente suspensas devido à alta demanda.\n"
            "Por favor, tente novamente mais tarde.",
            call.message.chat.id,
            call.message.message_id,
            parse_mode="Markdown",
            reply_markup=types.InlineKeyboardMarkup().add(
                types.InlineKeyboardButton("🔙 Voltar", callback_data="start")
            )
        )
        return
    
    # Check if user has pending payment
    pending_payment = get_user_pending_payment(user_id)
    if pending_payment:
        bot.answer_callback_query(call.id, "Você tem um pagamento pendente.")
        show_pending_payment(call)
        return
    
    # Create plans message
    plans_msg = "🛒 *Escolha um plano:* 🛒\n\n"
    
    for plan_id, plan in PLANS.items():
        # Calcular preço do plano e obter informações de desconto
        price, discount_info = calculate_plan_price(user_id, plan_id)
        is_first_buy = user.get('is_first_buy', True) if user else True
        
        plans_msg += f"*{plan['name']}*\n"
        plans_msg += f"Duração: {plan['duration_days']} dias\n"
        
        # Verificar se há desconto sazonal
        if 'seasonal_discount' in discount_info:
            seasonal = discount_info['seasonal_discount']
            original_price = seasonal['original_price']
            percent = seasonal['percent']
            expiration_date = seasonal['expiration_date']
            
            # Formatar data de expiração para legibilidade
            expire_date_str = expiration_date.strftime('%d/%m/%Y')
            days_left = (expiration_date - datetime.now()).days
            
            if is_first_buy and plan['first_buy_discount']:
                plans_msg += f"Preço: {format_currency(price)} *(Primeira compra!)*\n"
            else:
                plans_msg += f"Preço: ~~{format_currency(original_price)}~~ {format_currency(price)} \n"
            
            plans_msg += f"*🔥 PROMOÇÃO! {percent}% OFF* - Válido até {expire_date_str} ({days_left} dias restantes)\n"
        elif is_first_buy and plan['first_buy_discount']:
            plans_msg += f"Preço: {format_currency(price)} *(Primeira compra!)*\n"
        else:
            plans_msg += f"Preço: {format_currency(price)}\n"
        
        plans_msg += "\n"
    
    # Create keyboard
    keyboard = types.InlineKeyboardMarkup(row_width=1)
    
    # Add buttons for each plan
    for plan_id, plan in PLANS.items():
        # Criar callback_data com o ID exato como está no dicionário PLANS
        # Não incluir underscores no ID do plano para evitar problemas de parsing
        safe_plan_id = plan_id.replace("_", "-")
        callback_data = f"select_plan_{safe_plan_id}"
        logger.info(f"Creating plan button with callback_data: {callback_data}")
        
        # Calcular preço para exibir no botão (usando a versão atualizada que retorna o preço e informações de desconto)
        price, _ = calculate_plan_price(user_id, plan_id)
        
        keyboard.add(
            types.InlineKeyboardButton(
                f"🛍️ {plan['name']} - {format_currency(price)}",
                callback_data=callback_data
            )
        )
    
    # Add back button
    keyboard.add(types.InlineKeyboardButton("🔙 Voltar", callback_data="start"))
    
    # Edit message
    bot.edit_message_text(
        plans_msg,
        call.message.chat.id,
        call.message.message_id,
        reply_markup=keyboard,
        parse_mode="Markdown"
    )

# Select plan
@bot.callback_query_handler(func=lambda call: call.data.startswith("select_plan_"))
def select_plan(call):
    user_id = call.from_user.id
    parts = call.data.split("_")
    
    logger.info(f"Processing plan selection: {call.data}, parts: {parts}")
    
    # Verificar se o usuário já tem um pagamento pendente
    pending_payment = get_user_pending_payment(user_id)
    if pending_payment:
        bot.answer_callback_query(call.id, "Você já tem um pagamento pendente!")
        # Mostrar o pagamento pendente em vez de prosseguir
        show_pending_payment(call)
        return
    
    # Garantir que temos todas as partes necessárias
    if len(parts) < 3:
        bot.answer_callback_query(call.id, "Formato de plano inválido!")
        logger.error(f"Invalid plan format: {call.data}")
        show_plans(call)
        return
    
    # O ID do plano pode estar em diferentes formatos, verificar os possíveis
    # Restaurar os underscores usados nos IDs do plano (substituídos por hífens)
    plan_param = parts[2]
    
    # Converter o formato do callback para o formato usado no dicionário PLANS
    if plan_param == "30-days":
        plan_id = "30_days"
    elif plan_param == "6-months":
        plan_id = "6_months"
    elif plan_param == "1-year":
        plan_id = "1_year"
    else:
        # Tentar fazer a conversão direta substituindo hífens por underscores
        plan_id = plan_param.replace("-", "_")
        
    logger.info(f"Plan ID after parsing: {plan_id}")
    
    # Validar o plano e verificar se está no formato correto
    if plan_id not in PLANS:
        valid_plans = list(PLANS.keys())
        bot.answer_callback_query(call.id, f"Plano inválido! Planos válidos: {valid_plans}")
        logger.error(f"Invalid plan ID: {plan_id}, available plans: {valid_plans}")
        show_plans(call)
        return
    
    # Calculate price with seasonal discount info
    price, discount_info = calculate_plan_price(user_id, plan_id)
    
    # Check if user was referred for a discount (not first purchase)
    user = get_user(user_id)
    discounted_price, discount_applied = apply_referral_discount(user_id, price)
    
    # Create confirmation message
    confirm_msg = (
        f"🛒 *Confirmar Compra* 🛒\n\n"
        f"Plano: {PLANS[plan_id]['name']}\n"
        f"Duração: {PLANS[plan_id]['duration_days']} dias\n"
    )
    
    if discount_applied:
        confirm_msg += (
            f"Preço original: {format_currency(price)}\n"
            f"*Desconto por indicação aplicado!*\n"
            f"Preço final: {format_currency(discounted_price)}\n\n"
        )
        price = discounted_price
    else:
        confirm_msg += f"Preço: {format_currency(price)}\n\n"
    
    confirm_msg += "Deseja prosseguir com a compra?"
    
    # Format price for callback data as string without currency symbol
    price_str = str(price).replace('.', '_')
    
    # Log the callback data being created
    logger.info(f"Creating confirm button with callback_data: confirm_plan_{plan_id}_{price_str}")
    logger.info(f"Creating coupon button with callback_data: use_coupon_{plan_id}_{price_str}")
    
    # Create keyboard
    # Garantir que estamos usando o formato correto para o ID do plano nos callbacks
    safe_plan_id = plan_id.replace("_", "-")
    
    # Log para verificar o formato dos dados
    logger.info(f"Criando botões com plan_id: {plan_id}, safe_plan_id: {safe_plan_id}, price_str: {price_str}")
    
    # Criar teclado com os botões
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        types.InlineKeyboardButton("✅ Confirmar", callback_data=f"confirm_plan_{safe_plan_id}_{price_str}"),
        types.InlineKeyboardButton("❌ Cancelar", callback_data="show_plans")
    )
    
    # Add coupon button
    keyboard.add(
        types.InlineKeyboardButton("🎟️ Tenho um cupom", callback_data=f"use_coupon_{safe_plan_id}_{price_str}")
    )
    
    # Edit message
    bot.edit_message_text(
        confirm_msg,
        call.message.chat.id,
        call.message.message_id,
        reply_markup=keyboard,
        parse_mode="Markdown"
    )

# Use coupon
@bot.callback_query_handler(func=lambda call: call.data.startswith("use_coupon_"))
def use_coupon_callback(call):
    # Log the callback data for debugging
    logger.info(f"Processing coupon callback: {call.data}")
    
    # Extract data
    data_parts = call.data.split("_")
    
    # Ensure we have enough parts
    if len(data_parts) < 4:
        bot.answer_callback_query(call.id, "Formato de dados inválido!")
        logger.error(f"Invalid coupon data format: {call.data}")
        return
    
    plan_id = data_parts[2]
    
    # Convert string price back to float (format was like 20_00 for 20.00)
    try:
        # Try to handle both formats: float or underscore-separated
        if '.' in data_parts[3]:
            price = float(data_parts[3])
        else:
            price_str = data_parts[3].replace('_', '.')
            price = float(price_str)
            logger.info(f"Converted price from {data_parts[3]} to {price}")
    except ValueError:
        # If price conversion fails, recalculate it
        logger.error(f"Error converting price {data_parts[3]} to float")
        price, _ = calculate_plan_price(call.from_user.id, plan_id)
        logger.info(f"Recalculated price: {price}")
    
    # Check if user is eligible to use coupons (not first purchase)
    user_id = call.from_user.id
    user = get_user(user_id)
    
    if user and user.get('is_first_buy', True):
        bot.answer_callback_query(call.id, "Cupons não podem ser usados na primeira compra!")
        return
    
    # Create message
    coupon_msg = (
        f"🎟️ *Cupom de Desconto* 🎟️\n\n"
        f"Por favor, digite o código do cupom:"
    )
    
    # Edit message
    bot.edit_message_text(
        coupon_msg,
        call.message.chat.id,
        call.message.message_id,
        parse_mode="Markdown"
    )
    
    # Register the next step handler
    bot.register_next_step_handler(call.message, process_coupon_code, plan_id, price)

def process_coupon_code(message, plan_id, price):
    user_id = message.from_user.id
    coupon_code = message.text.strip()
    
    # Garantir que o ID do plano está no formato correto
    if plan_id.replace("-", "_") in PLANS:
        # Se tiver hífen, converter para underscore
        plan_id = plan_id.replace("-", "_")
    
    # Validate coupon
    coupon_result, msg = validate_coupon(coupon_code, user_id, plan_id, price)
    
    if not coupon_result:
        # Invalid coupon
        # Usar hífen em vez de underscore no plano para o callback
        safe_plan_id = plan_id.replace("_", "-")
        # Formatar preço para callback
        price_str = str(price).replace('.', '_')
        
        keyboard = types.InlineKeyboardMarkup(row_width=2)
        keyboard.add(
            types.InlineKeyboardButton("🔙 Voltar", callback_data=f"select_plan_{safe_plan_id}"),
            types.InlineKeyboardButton("🎟️ Tentar outro cupom", callback_data=f"use_coupon_{safe_plan_id}_{price_str}")
        )
        
        bot.send_message(
            message.chat.id,
            f"❌ *Erro ao aplicar cupom* ❌\n\n{msg}",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        return
    
    # Valid coupon
    discount = coupon_result['discount']
    final_price = coupon_result['final_amount']
    
    # Registrar o uso do cupom imediatamente
    coupon_code = coupon_code.strip().upper()
    use_coupon(coupon_code, user_id)
    logger.info(f"Coupon {coupon_code} usage registered for user {user_id}")
    
    # Create confirmation message with discount
    confirm_msg = (
        f"🎟️ *Cupom Aplicado com Sucesso!* 🎟️\n\n"
        f"Plano: {PLANS[plan_id]['name']}\n"
        f"Duração: {PLANS[plan_id]['duration_days']} dias\n"
        f"Preço original: {format_currency(price)}\n"
        f"Desconto: {format_currency(discount)}\n"
        f"Preço final: {format_currency(final_price)}\n\n"
        f"Deseja prosseguir com a compra?"
    )
    
    # Create keyboard
    # Usar formato seguro para o ID do plano
    safe_plan_id = plan_id.replace("_", "-")
    final_price_str = str(final_price).replace('.', '_')
    
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        types.InlineKeyboardButton("✅ Confirmar", callback_data=f"confirm_plan_{safe_plan_id}_{final_price_str}_{coupon_code}"),
        types.InlineKeyboardButton("❌ Cancelar", callback_data="show_plans")
    )
    
    # Send message
    bot.send_message(
        message.chat.id,
        confirm_msg,
        reply_markup=keyboard,
        parse_mode="Markdown"
    )

# Confirm plan
@bot.callback_query_handler(func=lambda call: call.data.startswith("confirm_plan_"))
def confirm_plan(call):
    # Log the callback data for debugging
    logger.info(f"Processing confirm plan callback: {call.data}")
    
    # Extract data
    data_parts = call.data.split("_")
    
    # Ensure we have enough parts
    if len(data_parts) < 4:
        bot.answer_callback_query(call.id, "Formato de dados inválido!")
        logger.error(f"Invalid confirm plan data format: {call.data}")
        return
    
    plan_id = data_parts[2]
    
    # Converter hífens para underscores (formato aceito no dicionário PLANS)
    if plan_id.replace("-", "_") in PLANS:
        plan_id = plan_id.replace("-", "_")
    
    logger.info(f"Plan ID in confirm plan after parsing: {plan_id}")
    
    # Garantir que o plano existe
    if plan_id not in PLANS:
        valid_plans = list(PLANS.keys())
        bot.answer_callback_query(call.id, f"Plano inválido! Planos válidos: {valid_plans}")
        logger.error(f"Invalid plan ID: {plan_id}, available plans: {valid_plans}")
        show_plans(call)
        return
    
    # Convert string price back to float (format was like 20_00 for 20.00)
    try:
        # Try to handle both formats: float or underscore-separated
        if '.' in data_parts[3]:
            price = float(data_parts[3])
        else:
            price_str = data_parts[3].replace('_', '.')
            price = float(price_str)
            logger.info(f"Converted price from {data_parts[3]} to {price}")
    except ValueError:
        # If price conversion fails, recalculate it
        logger.error(f"Error converting price {data_parts[3]} to float")
        price, _ = calculate_plan_price(call.from_user.id, plan_id)
        logger.info(f"Recalculated price: {price}")
    
    coupon_code = data_parts[4] if len(data_parts) > 4 else None
    
    user_id = call.from_user.id
    
    # Check if Mercado Pago is enabled
    bot_config = read_json_file(BOT_CONFIG_FILE)
    payment_settings = bot_config.get('payment_settings', {})
    mercado_pago_settings = payment_settings.get('mercado_pago', {})
    
    # If Mercado Pago is enabled and configured
    has_mercado_pago = (
        mercado_pago_settings.get('enabled', False) and 
        mercado_pago_settings.get('access_token') and 
        mercado_pago_settings.get('public_key')
    )
    
    # Create payment
    payment_id = create_payment(user_id, plan_id, price, coupon_code)
    
    # Create message - Default to PIX payment
    payment_msg = (
        f"💰 *Pagamento - {PLANS[plan_id]['name']}* 💰\n\n"
        f"Para concluir sua compra, precisamos de algumas informações:\n\n"
        f"Por favor, informe seu Nome Completo ou CNPJ:"
    )
    
    # Edit message
    bot.edit_message_text(
        payment_msg,
        call.message.chat.id,
        call.message.message_id,
        parse_mode="Markdown"
    )
    
    # Register next step
    bot.register_next_step_handler(call.message, process_payer_name, payment_id)

def process_payer_name(message, payment_id):
    payer_name = message.text.strip()
    
    # Validate name
    if len(payer_name) < 3:
        bot.send_message(
            message.chat.id,
            "❌ Nome muito curto. Por favor, informe seu nome completo ou CNPJ:"
        )
        bot.register_next_step_handler(message, process_payer_name, payment_id)
        return
    
    # Update payment with payer name
    payment = get_payment(payment_id)
    if not payment:
        bot.send_message(
            message.chat.id,
            "❌ Erro ao processar pagamento. Por favor, inicie o processo novamente com /start."
        )
        return
    
    update_payment(payment_id, {'payer_name': payer_name})
    
    # Send payment options
    plan_id = payment['plan_type']
    amount = payment['amount']
    
    # Get payment settings from bot_config
    bot_config = read_json_file(BOT_CONFIG_FILE)
    payment_settings = bot_config.get('payment_settings', {})
    
    # Check if Mercado Pago is enabled
    mercado_pago_settings = payment_settings.get('mercado_pago', {})
    has_mercado_pago = (
        mercado_pago_settings.get('enabled', False) and
        mercado_pago_settings.get('access_token') and
        mercado_pago_settings.get('public_key')
    )
    
    # Sempre oferecer seleção de método de pagamento
    select_msg = (
        f"💰 *Escolha seu método de pagamento* 💰\n\n"
        f"Plano: {PLANS[plan_id]['name']}\n"
        f"Valor: {format_currency(amount)}\n\n"
        f"Selecione como deseja pagar:"
    )
    
    # Create payment method keyboard
    keyboard = types.InlineKeyboardMarkup(row_width=1)
    
    # Sempre adicionar PIX Manual
    keyboard.add(
        types.InlineKeyboardButton("💸 PIX Manual (Transferência)", callback_data=f"pay_pix_manual_{payment_id}")
    )
    
    # Adicionar opção de PIX via Mercado Pago se configurado
    if has_mercado_pago:
        keyboard.add(
            types.InlineKeyboardButton("📱 PIX com QR Code (Mercado Pago)", callback_data=f"pay_pix_mp_{payment_id}")
        )
    
    # Botão de Cancelar
    keyboard.add(
        types.InlineKeyboardButton("❌ Cancelar Pagamento", callback_data=f"cancel_payment_{payment_id}")
    )
    
    # Send payment selection message
    bot.send_message(
        message.chat.id,
        select_msg,
        reply_markup=keyboard,
        parse_mode="Markdown"
    )

# Function to send PIX payment instructions
def send_pix_instructions(message, payment_id):
    # Get payment details
    payment = get_payment(payment_id)
    if not payment:
        # Handle different types of message objects
        if isinstance(message, types.CallbackQuery):
            chat_id = message.message.chat.id
        else:
            chat_id = message.chat.id
        
        bot.send_message(
            chat_id,
            "❌ Erro ao processar pagamento. Por favor, inicie o processo novamente com /start."
        )
        return
    
    plan_id = payment['plan_type']
    amount = payment['amount']
    
    # Get PIX settings from bot_config
    bot_config = read_json_file(BOT_CONFIG_FILE)
    pix_settings = bot_config.get('payment_settings', {}).get('pix', {})
    
    pix_key = pix_settings.get('key', 'nossaempresa@email.com')
    pix_name = pix_settings.get('name', 'Empresa UniTV LTDA')
    pix_bank = pix_settings.get('bank', 'Banco UniTV')
    
    # Get user ID based on message type
    if isinstance(message, types.CallbackQuery):
        user_id = message.from_user.id
    else:
        user_id = message.from_user.id
    
    pix_msg = (
        f"🏦 *Informações para Pagamento PIX Manual* 🏦\n\n"
        f"Plano: {PLANS[plan_id]['name']}\n"
        f"Valor: {format_currency(amount)}\n\n"
        f"*Chave PIX:* `{pix_key}`\n\n"
        f"Nome: {pix_name}\n"
        f"Banco: {pix_bank}\n\n"
        f"*Instruções:*\n"
        f"1. Abra seu aplicativo bancário\n"
        f"2. Escolha a opção PIX\n"
        f"3. Cole a chave PIX acima\n"
        f"4. Informe o valor exato: {format_currency(amount)}\n"
        f"5. Na descrição, escreva seu ID Telegram: {user_id}\n\n"
        f"Após realizar o pagamento, clique no botão 'Confirmar Pagamento' abaixo."
    )
    
    # Create keyboard
    keyboard = types.InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        types.InlineKeyboardButton("✅ Confirmar Pagamento", callback_data=f"payment_done_{payment_id}"),
        types.InlineKeyboardButton("❌ Cancelar Pagamento", callback_data=f"cancel_payment_{payment_id}")
    )
    
    # Send message
    if isinstance(message, types.CallbackQuery):
        # If coming from a callback, edit the message
        msg = bot.edit_message_text(
            pix_msg,
            message.message.chat.id,
            message.message.message_id,
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        # Registrar esta mensagem como relacionada ao pagamento
        chat_id = message.message.chat.id
        message_id = message.message.message_id
    else:
        # If coming from a text message, send a new message
        msg = bot.send_message(
            message.chat.id,
            pix_msg,
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        chat_id = message.chat.id
        message_id = msg.message_id
        
    # Registrar esta mensagem como relacionada ao pagamento
    payment = get_payment(payment_id)
    if payment and 'related_messages' in payment:
        related_messages = payment['related_messages']
        message_info = {'chat_id': chat_id, 'message_id': message_id}
        if message_info not in related_messages:
            related_messages.append(message_info)
            update_payment(payment_id, {'related_messages': related_messages})
            logger.info(f"Registered message {message_id} as related to payment {payment_id}")

# Handler for PIX Manual payment method selection
@bot.callback_query_handler(func=lambda call: call.data.startswith("pay_pix_manual_"))
def pay_with_pix_manual(call):
    payment_id = call.data.split("_")[3]
    send_pix_instructions(call, payment_id)

import requests
import json
import uuid
import os

# Handler for PIX via Mercado Pago payment method selection
@bot.callback_query_handler(func=lambda call: call.data.startswith("pay_pix_mp_"))
def pay_with_pix_mercado_pago(call):
    payment_id = call.data.split("_")[3]
    
    # Get payment details
    payment = get_payment(payment_id)
    if not payment:
        bot.answer_callback_query(call.id, "Pagamento não encontrado!")
        return
    
    plan_id = payment['plan_type']
    amount = payment['amount']
    
    # Verificar se já há um pagamento Mercado Pago ativo para este pagamento
    if payment.get('mp_payment_id'):
        # Mostrar mensagem temporária enquanto processa
        temp_msg = bot.edit_message_text(
            "⏳ *Verificando pagamento existente...* ⏳\n\nPor favor, aguarde um momento.",
            call.message.chat.id,
            call.message.message_id,
            parse_mode="Markdown"
        )
        
        # Get Mercado Pago settings
        bot_config = read_json_file(BOT_CONFIG_FILE)
        mp_settings = bot_config.get('payment_settings', {}).get('mercado_pago', {})
        access_token = mp_settings.get('access_token')
        
        if access_token:
            # Verificar status do pagamento no Mercado Pago
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json"
            }
            
            try:
                mp_status_response = requests.get(
                    f"https://api.mercadopago.com/v1/payments/{payment['mp_payment_id']}",
                    headers=headers
                )
                
                if mp_status_response.status_code == 200:
                    mp_payment_data = mp_status_response.json()
                    mp_status = mp_payment_data.get('status')
                    
                    # Se o pagamento estiver pendente, mostrar novamente o QR code
                    if mp_status in ['pending', 'in_process', 'authorized']:
                        # Obter os dados do PIX
                        pix_data = mp_payment_data.get('point_of_interaction', {}).get('transaction_data', {})
                        qr_code = pix_data.get('qr_code', '')
                        
                        # Criar a mensagem com as instruções
                        mp_msg = (
                            f"📱 *PIX com QR Code via Mercado Pago* 📱\n\n"
                            f"Plano: {PLANS[plan_id]['name']}\n"
                            f"Valor: {format_currency(amount)}\n\n"
                            f"*Instruções:*\n"
                            f"1. Copie o código PIX abaixo ou use o botão para abrir o QR Code\n"
                            f"2. Abra o aplicativo do seu banco\n"
                            f"3. Escolha PIX > Pagar com PIX > Copia e Cola\n"
                            f"4. Cole o código e confirme o pagamento\n\n"
                            f"*Código PIX (Copia e Cola):*\n`{qr_code}`\n\n"
                            f"*O pagamento será confirmado automaticamente* assim que for processado.\n\n"
                            f"⏰ *ATENÇÃO: Este QR Code expira em 10 minutos* ⏰"
                        )
                        
                        # Criar o teclado
                        keyboard = types.InlineKeyboardMarkup(row_width=1)
                        
                        # Adicionar botão para ver o QR Code
                        if 'qr_code_url' in pix_data:
                            qr_url = pix_data['qr_code_url']
                            keyboard.add(
                                types.InlineKeyboardButton(text="📱 Ver QR Code PIX", url=qr_url)
                            )
                        
                        # Adicionar outros botões
                        keyboard.add(
                            types.InlineKeyboardButton("❌ Cancelar Pagamento", callback_data=f"cancel_payment_{payment_id}"),
                            types.InlineKeyboardButton("↩️ Voltar para PIX Manual", callback_data=f"pay_pix_manual_{payment_id}")
                        )
                        
                        # Editar mensagem com instruções atualizadas
                        msg = bot.edit_message_text(
                            mp_msg,
                            call.message.chat.id,
                            call.message.message_id,
                            reply_markup=keyboard,
                            parse_mode="Markdown"
                        )
                        
                        # Registrar esta mensagem como relacionada ao pagamento (se ainda não estiver registrada)
                        if payment and 'related_messages' in payment:
                            related_messages = payment['related_messages']
                            message_info = {'chat_id': call.message.chat.id, 'message_id': call.message.message_id}
                            if message_info not in related_messages:
                                related_messages.append(message_info)
                                update_payment(payment_id, {'related_messages': related_messages})
                                logger.info(f"Registered message {call.message.message_id} as related to existing payment {payment_id}")
                        return
                    else:
                        # O pagamento já foi processado, cancelado ou teve outro status final
                        # Vamos criar um novo
                        # Primeiro cancelar o pagamento atual para não sobrecarregar a API
                        _cancel_mercado_pago_payment(payment['mp_payment_id'])
                        # Continuar para criar um novo pagamento
                else:
                    # Erro ao verificar status, vamos criar um novo
                    logger.warning(f"Failed to check MP payment status: {mp_status_response.status_code}")
            except Exception as e:
                logger.error(f"Error checking MP payment status: {e}")
                # Continuar para criar um novo pagamento
    
    # Get Mercado Pago settings
    bot_config = read_json_file(BOT_CONFIG_FILE)
    mp_settings = bot_config.get('payment_settings', {}).get('mercado_pago', {})
    
    # Check if Mercado Pago is enabled
    if not mp_settings.get('enabled') or not mp_settings.get('access_token'):
        bot.answer_callback_query(call.id, "Mercado Pago não está disponível no momento.")
        # Fallback to PIX manual
        send_pix_instructions(call, payment_id)
        return
    
    # Mostrar mensagem temporária enquanto processa
    temp_msg = bot.edit_message_text(
        "⏳ *Gerando QR Code PIX...* ⏳\n\nPor favor, aguarde um momento.",
        call.message.chat.id,
        call.message.message_id,
        parse_mode="Markdown"
    )
    
    try:
        # Obter o token de acesso do Mercado Pago
        access_token = mp_settings.get('access_token')
        
        # Preparar dados do pagamento com expiração de 10 minutos
        payment_data = {
            "transaction_amount": float(amount),
            "description": f"UniTV - {PLANS[plan_id]['name']} - ID: {payment_id}",
            "payment_method_id": "pix",
            "payer": {
                "email": f"cliente_{call.from_user.id}@unitv.com",
                "first_name": call.from_user.first_name or "Cliente",
                "last_name": call.from_user.last_name or "UniTV",
                "identification": {
                    "type": "CPF",
                    "number": "00000000000"  # CPF fictício, em produção usar CPF real
                }
            },
            # Adicionar data de expiração do PIX (10 minutos) no formato correto
            "date_of_expiration": (datetime.now() + timedelta(minutes=10)).strftime('%Y-%m-%dT%H:%M:%S.000Z'),
            "notification_url": "https://unitv-subscription-bot.replit.app/webhooks/mercadopago"  # URL real para notificações
        }
        
        # Configurar headers
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "X-Idempotency-Key": str(uuid.uuid4())  # Adicionar cabeçalho de idempotência
        }
        
        # Fazer requisição à API do Mercado Pago
        response = requests.post(
            "https://api.mercadopago.com/v1/payments",
            data=json.dumps(payment_data),
            headers=headers
        )
        
        # Verificar resposta
        if response.status_code == 201:
            # Pagamento criado com sucesso
            mp_response = response.json()
            logger.info(f"Mercado Pago payment created: {mp_response['id']}")
            
            # Salvar o ID do pagamento MP no nosso pagamento
            update_payment(payment_id, {'mp_payment_id': mp_response['id']})
            
            # Obter os dados do PIX
            pix_data = mp_response.get('point_of_interaction', {}).get('transaction_data', {})
            qr_code_base64 = pix_data.get('qr_code_base64', '')
            qr_code = pix_data.get('qr_code', '')
            
            # Criar a mensagem com as instruções
            mp_msg = (
                f"📱 *PIX com QR Code via Mercado Pago* 📱\n\n"
                f"Plano: {PLANS[plan_id]['name']}\n"
                f"Valor: {format_currency(amount)}\n\n"
                f"*Instruções:*\n"
                f"1. Copie o código PIX abaixo ou use o botão para abrir o QR Code\n"
                f"2. Abra o aplicativo do seu banco\n"
                f"3. Escolha PIX > Pagar com PIX > Copia e Cola\n"
                f"4. Cole o código e confirme o pagamento\n\n"
                f"*Código PIX (Copia e Cola):*\n`{qr_code}`\n\n"
                f"*O pagamento será confirmado automaticamente* assim que for processado.\n\n"
                f"⏰ *ATENÇÃO: Este QR Code expira em 10 minutos* ⏰"
            )
            
            # Criar o teclado
            keyboard = types.InlineKeyboardMarkup(row_width=1)
            
            # Adicionar botão para ver o QR Code
            if 'qr_code_url' in pix_data:
                qr_url = pix_data['qr_code_url']
                keyboard.add(
                    types.InlineKeyboardButton(text="📱 Ver QR Code PIX", url=qr_url)
                )
            
            # Adicionar outros botões
            keyboard.add(
                types.InlineKeyboardButton("❌ Cancelar Pagamento", callback_data=f"cancel_payment_{payment_id}"),
                types.InlineKeyboardButton("↩️ Voltar para PIX Manual", callback_data=f"pay_pix_manual_{payment_id}")
            )
            
            # Enviar QR code como parte da mesma mensagem (se disponível)
            # Em vez de enviar uma imagem separada, vamos incorporar tudo na mesma mensagem
            # para não sobrecarregar a API do Telegram e facilitar o fluxo do usuário
            
            # Editar mensagem com instruções
            msg = bot.edit_message_text(
                mp_msg,
                call.message.chat.id,
                call.message.message_id,
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
            
            # Registrar esta mensagem como relacionada ao pagamento
            payment = get_payment(payment_id)
            if payment and 'related_messages' in payment:
                related_messages = payment['related_messages']
                message_info = {'chat_id': call.message.chat.id, 'message_id': call.message.message_id}
                if message_info not in related_messages:
                    related_messages.append(message_info)
                    update_payment(payment_id, {'related_messages': related_messages})
                    logger.info(f"Registered message {call.message.message_id} as related to payment {payment_id}")
            
        else:
            # Erro ao criar pagamento no Mercado Pago
            try:
                error_response = response.json()
                error_msg = error_response.get('message', 'Erro desconhecido')
                error_detail = error_response.get('error', '')
                response_status = response.status_code
                logger.error(f"Mercado Pago payment error: Status: {response_status}, Message: {error_msg}, Detail: {error_detail}")
                logger.error(f"Full Mercado Pago error response: {error_response}")
            except Exception as json_error:
                logger.error(f"Error parsing Mercado Pago response: {json_error}")
                logger.error(f"Raw response: {response.text}")
            
            bot.edit_message_text(
                f"❌ *Erro ao gerar QR Code PIX* ❌\n\n"
                f"Não foi possível gerar o pagamento via Mercado Pago.\n"
                f"Por favor, tente pagar usando o PIX Manual.",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=types.InlineKeyboardMarkup().add(
                    types.InlineKeyboardButton("↩️ Usar PIX Manual", callback_data=f"pay_pix_manual_{payment_id}")
                ),
                parse_mode="Markdown"
            )
    
    except Exception as e:
        # Tratar qualquer erro durante o processo
        import traceback
        error_traceback = traceback.format_exc()
        logger.error(f"Error creating Mercado Pago payment: {e}")
        logger.error(f"Detailed traceback: {error_traceback}")
        
        # Verificar se é um erro de token de acesso (autenticação)
        auth_error = False
        if hasattr(e, 'args') and len(e.args) > 0:
            error_msg = str(e.args[0])
            if 'authentication' in error_msg.lower() or 'token' in error_msg.lower() or 'unauthorized' in error_msg.lower():
                auth_error = True
                logger.error("Identified authentication error with Mercado Pago API")
        
        # Mensagem específica se for erro de autenticação
        if auth_error:
            bot.edit_message_text(
                f"❌ *Erro de autenticação no Mercado Pago* ❌\n\n"
                f"Não foi possível autenticar com a API do Mercado Pago.\n"
                f"Por favor, tente usar o PIX Manual enquanto o problema é corrigido.",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=types.InlineKeyboardMarkup().add(
                    types.InlineKeyboardButton("↩️ Usar PIX Manual", callback_data=f"pay_pix_manual_{payment_id}")
                ),
                parse_mode="Markdown"
            )
        else:
            # Mensagem genérica para outros erros
            bot.edit_message_text(
                f"❌ *Erro ao gerar QR Code PIX* ❌\n\n"
                f"Ocorreu um erro ao processar seu pagamento via Mercado Pago.\n"
                f"Por favor, tente pagar usando o PIX Manual.",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=types.InlineKeyboardMarkup().add(
                    types.InlineKeyboardButton("↩️ Usar PIX Manual", callback_data=f"pay_pix_manual_{payment_id}")
                ),
                parse_mode="Markdown"
            )

# Legacy handler for compatibility - redirect to manual PIX
@bot.callback_query_handler(func=lambda call: call.data.startswith("pay_pix_") and not call.data.startswith("pay_pix_manual_") and not call.data.startswith("pay_pix_mp_"))
def pay_with_pix_legacy(call):
    parts = call.data.split("_")
    if len(parts) >= 3:
        payment_id = parts[2]
        send_pix_instructions(call, payment_id)

# Payment done
@bot.callback_query_handler(func=lambda call: call.data.startswith("payment_done_"))
def payment_done(call):
    payment_id = call.data.split("_")[2]
    
    # Get payment details
    payment = get_payment(payment_id)
    if not payment:
        bot.answer_callback_query(call.id, "Pagamento não encontrado!")
        return
    
    # Update payment status
    update_payment(payment_id, {'status': 'pending_approval'})
    
    # Notify admin
    admin_msg = (
        f"💰 *Novo Pagamento Pendente* 💰\n\n"
        f"*ID do Pagamento:* {payment_id}\n"
        f"*Usuário:* {call.from_user.first_name} {call.from_user.last_name or ''} (@{call.from_user.username or 'sem_username'})\n"
        f"*ID do Usuário:* {call.from_user.id}\n"
        f"*Plano:* {PLANS[payment['plan_type']]['name']}\n"
        f"*Valor:* {format_currency(payment['amount'])}\n"
        f"*Nome do Pagador:* {payment['payer_name']}\n\n"
        f"Por favor, verifique o pagamento e aprove ou rejeite."
    )
    
    # Create admin keyboard
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        types.InlineKeyboardButton("✅ Aprovar", callback_data=f"approve_payment_{payment_id}"),
        types.InlineKeyboardButton("❌ Rejeitar", callback_data=f"reject_payment_{payment_id}")
    )
    
    # Send admin notification
    bot.send_message(
        ADMIN_ID,
        admin_msg,
        reply_markup=keyboard,
        parse_mode="Markdown"
    )
    
    # Update user
    confirmation_msg = (
        f"✅ *Pagamento Enviado para Aprovação* ✅\n\n"
        f"Seu pagamento foi registrado e enviado para aprovação do administrador.\n"
        f"Você receberá uma notificação assim que for aprovado.\n\n"
        f"ID do Pagamento: `{payment_id}`\n"
        f"Plano: {PLANS[payment['plan_type']]['name']}\n"
        f"Valor: {format_currency(payment['amount'])}"
    )
    
    # Edit message
    bot.edit_message_text(
        confirmation_msg,
        call.message.chat.id,
        call.message.message_id,
        parse_mode="Markdown",
        reply_markup=types.InlineKeyboardMarkup().add(
            types.InlineKeyboardButton("🔙 Voltar ao Início", callback_data="start")
        )
    )

# Cancel payment
@bot.callback_query_handler(func=lambda call: call.data.startswith("cancel_payment_"))
def cancel_payment_callback(call):
    payment_id = call.data.split("_")[2]
    
    try:
        # Obter dados do pagamento antes de cancelar
        payment = get_payment(payment_id)
        
        # Se for um pagamento do Mercado Pago e tiver um ID de pagamento MP, cancelar na API do MP
        if payment and payment.get('mp_payment_id'):
            logger.info(f"Canceling Mercado Pago payment: {payment.get('mp_payment_id')}")
            
            try:
                # Obter o token do Mercado Pago
                bot_config = read_json_file(BOT_CONFIG_FILE)
                mp_settings = bot_config.get('payment_settings', {}).get('mercado_pago', {})
                access_token = mp_settings.get('access_token')
                
                if access_token:
                    # Tentar cancelar o pagamento no Mercado Pago
                    headers = {
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "application/json",
                        "X-Idempotency-Key": str(uuid.uuid4())
                    }
                    
                    # Verificar o status atual do pagamento
                    mp_payment_id = payment.get('mp_payment_id')
                    mp_status_response = requests.get(
                        f"https://api.mercadopago.com/v1/payments/{mp_payment_id}",
                        headers=headers
                    )
                    
                    if mp_status_response.status_code == 200:
                        mp_payment_data = mp_status_response.json()
                        mp_status = mp_payment_data.get('status')
                        
                        # Se o pagamento ainda estiver pendente, cancelá-lo
                        if mp_status in ['pending', 'in_process', 'authorized']:
                            cancel_data = {"status": "cancelled"}
                            mp_cancel_response = requests.put(
                                f"https://api.mercadopago.com/v1/payments/{mp_payment_id}",
                                headers=headers,
                                json=cancel_data
                            )
                            
                            if mp_cancel_response.status_code in [200, 201]:
                                logger.info(f"Mercado Pago payment {mp_payment_id} successfully cancelled")
                            else:
                                logger.warning(f"Failed to cancel Mercado Pago payment {mp_payment_id}: {mp_cancel_response.status_code}")
                        else:
                            logger.info(f"Mercado Pago payment {mp_payment_id} already in final state: {mp_status}")
                    else:
                        logger.warning(f"Failed to get Mercado Pago payment status: {mp_status_response.status_code}")
            except Exception as e:
                logger.error(f"Error cancelling Mercado Pago payment: {e}")
    except Exception as e:
        logger.error(f"Error in payment cancellation pre-processing: {e}")
    
    # Cancel the payment in our system regardless of MP API result
    success, payment = cancel_payment(payment_id)
    if success:
        bot.answer_callback_query(call.id, "Pagamento cancelado com sucesso!")
        
        cancel_message = (
            "❌ *Pagamento Cancelado* ❌\n\n"
            "Seu pagamento foi cancelado com sucesso.\n"
            "Você pode iniciar uma nova compra quando desejar."
        )
        
        cancel_keyboard = types.InlineKeyboardMarkup().add(
            types.InlineKeyboardButton("🔙 Voltar ao Início", callback_data="start")
        )
        
        # Editar a mensagem atual que iniciou o cancelamento
        bot.edit_message_text(
            cancel_message,
            call.message.chat.id,
            call.message.message_id,
            parse_mode="Markdown",
            reply_markup=cancel_keyboard
        )
        
        # Editar todas as outras mensagens relacionadas ao pagamento
        if payment and 'related_messages' in payment:
            related_messages = payment['related_messages']
            
            # Construir lista de mensagens únicas (excluindo a atual)
            current_msg = {'chat_id': call.message.chat.id, 'message_id': call.message.message_id}
            
            for msg_info in related_messages:
                # Verificar se não é a mensagem atual
                if msg_info.get('chat_id') != current_msg['chat_id'] or msg_info.get('message_id') != current_msg['message_id']:
                    try:
                        bot.edit_message_text(
                            cancel_message,
                            msg_info.get('chat_id'),
                            msg_info.get('message_id'),
                            parse_mode="Markdown",
                            reply_markup=cancel_keyboard
                        )
                        logger.info(f"Edited message {msg_info.get('message_id')} in chat {msg_info.get('chat_id')} for cancelled payment {payment_id}")
                    except Exception as edit_err:
                        logger.error(f"Error editing message {msg_info.get('message_id')} for payment {payment_id}: {edit_err}")
    else:
        bot.answer_callback_query(call.id, "Erro ao cancelar pagamento!")

# Admin: Approve payment
@bot.callback_query_handler(func=lambda call: call.data.startswith("approve_payment_"))
def approve_payment(call):
    # Check if admin
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "Apenas administradores podem aprovar pagamentos!")
        return
    
    payment_id = call.data.split("_")[2]
    payment = get_payment(payment_id)
    
    if not payment:
        bot.answer_callback_query(call.id, "Pagamento não encontrado!")
        return
    
    # Update payment status
    update_payment(payment_id, {
        'status': 'approved',
        'approved_at': datetime.now().isoformat()
    })
    
    # Check if login is available
    user_id = payment['user_id']
    plan_type = payment['plan_type']
    
    login = get_available_login(plan_type)
    
    if login:
        # Assign login to user
        assigned_login = assign_login_to_user(user_id, plan_type, payment_id)
        
        if assigned_login:
            # Notify user
            bot.send_message(
                user_id,
                f"🎉 *Seu login UniTV está pronto!* 🎉\n\n"
                f"Login: `{assigned_login}`\n\n"
                f"Seu plano expira em {PLANS[plan_type]['duration_days']} dias.\n"
                f"Aproveite sua assinatura UniTV! 📺✨",
                parse_mode="Markdown"
            )
            
            # Notify admin
            bot.edit_message_text(
                f"✅ *Pagamento Aprovado e Login Enviado* ✅\n\n"
                f"ID do Pagamento: {payment_id}\n"
                f"Usuário: {user_id}\n"
                f"Plano: {PLANS[plan_type]['name']}\n"
                f"Login enviado: `{assigned_login}`",
                call.message.chat.id,
                call.message.message_id,
                parse_mode="Markdown"
            )
            
            # If coupon was used, mark it as used
            if payment.get('coupon_code'):
                use_coupon(payment['coupon_code'], user_id)
    else:
        # No login available
        bot.edit_message_text(
            f"⚠️ *Pagamento Aprovado, mas Sem Login Disponível* ⚠️\n\n"
            f"O pagamento foi aprovado, mas não há logins disponíveis para o plano {PLANS[plan_type]['name']}.\n\n"
            f"Por favor, adicione novos logins usando /addlogin e o login será enviado automaticamente ao usuário.",
            call.message.chat.id,
            call.message.message_id,
            parse_mode="Markdown"
        )
        
        # Notify user
        bot.send_message(
            user_id,
            f"✅ *Pagamento Aprovado!* ✅\n\n"
            f"Seu pagamento para o plano {PLANS[plan_type]['name']} foi aprovado!\n\n"
            f"Estamos preparando seu login e você o receberá automaticamente em breve.\n"
            f"Obrigado pela paciência!",
            parse_mode="Markdown"
        )

# Admin: Reject payment
@bot.callback_query_handler(func=lambda call: call.data.startswith("reject_payment_"))
def reject_payment(call):
    # Check if admin
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "Apenas administradores podem rejeitar pagamentos!")
        return
    
    payment_id = call.data.split("_")[2]
    payment = get_payment(payment_id)
    
    if not payment:
        bot.answer_callback_query(call.id, "Pagamento não encontrado!")
        return
    
    # Se for um pagamento do Mercado Pago, cancelar na API
    if payment.get('mp_payment_id'):
        try:
            # Obter o token do Mercado Pago
            bot_config = read_json_file(BOT_CONFIG_FILE)
            mp_settings = bot_config.get('payment_settings', {}).get('mercado_pago', {})
            access_token = mp_settings.get('access_token')
            
            if access_token:
                # Configurar headers
                headers = {
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                    "X-Idempotency-Key": str(uuid.uuid4())
                }
                
                # Verificar o status atual do pagamento
                mp_payment_id = payment.get('mp_payment_id')
                mp_status_response = requests.get(
                    f"https://api.mercadopago.com/v1/payments/{mp_payment_id}",
                    headers=headers
                )
                
                if mp_status_response.status_code == 200:
                    mp_payment_data = mp_status_response.json()
                    mp_status = mp_payment_data.get('status')
                    
                    # Se o pagamento ainda estiver pendente, cancelá-lo
                    if mp_status in ['pending', 'in_process', 'authorized']:
                        cancel_data = {"status": "cancelled"}
                        mp_cancel_response = requests.put(
                            f"https://api.mercadopago.com/v1/payments/{mp_payment_id}",
                            headers=headers,
                            json=cancel_data
                        )
                        
                        if mp_cancel_response.status_code in [200, 201]:
                            logger.info(f"Mercado Pago payment {mp_payment_id} successfully cancelled upon rejection")
                        else:
                            logger.warning(f"Failed to cancel Mercado Pago payment {mp_payment_id} upon rejection: {mp_cancel_response.status_code}")
                    else:
                        logger.info(f"Mercado Pago payment {mp_payment_id} already in final state: {mp_status}")
                else:
                    logger.warning(f"Failed to get Mercado Pago payment status for rejection: {mp_status_response.status_code}")
        except Exception as e:
            logger.error(f"Error cancelling Mercado Pago payment upon rejection: {e}")
    
    # Update payment status
    update_payment(payment_id, {'status': 'rejected'})
    
    # Notify user
    bot.send_message(
        payment['user_id'],
        f"❌ *Pagamento Rejeitado* ❌\n\n"
        f"Seu pagamento para o plano {PLANS[payment['plan_type']]['name']} foi rejeitado.\n\n"
        f"Isso pode acontecer se o pagamento não foi encontrado ou se houve algum problema na transação.\n"
        f"Por favor, tente novamente ou entre em contato com o suporte.",
        parse_mode="Markdown"
    )
    
    # Update admin message
    bot.edit_message_text(
        f"❌ *Pagamento Rejeitado* ❌\n\n"
        f"ID do Pagamento: {payment_id}\n"
        f"Usuário: {payment['user_id']}\n"
        f"Plano: {PLANS[payment['plan_type']]['name']}",
        call.message.chat.id,
        call.message.message_id,
        parse_mode="Markdown"
    )

# Show pending payment
def show_pending_payment(call):
    user_id = call.from_user.id
    payment = get_user_pending_payment(user_id)
    
    if not payment:
        bot.answer_callback_query(call.id, "Você não tem pagamentos pendentes.")
        return
    
    payment_id = payment['payment_id']
    
    # Create message
    payment_msg = (
        f"💰 *Você tem um Pagamento Pendente* 💰\n\n"
        f"Plano: {PLANS[payment['plan_type']]['name']}\n"
        f"Valor: {format_currency(payment['amount'])}\n"
        f"Status: {get_payment_status_text(payment['status'])}\n\n"
    )
    
    # Calcular tempo restante até expiração (se for pagamento pendente com Mercado Pago)
    expiration_info = ""
    if payment['status'] == 'pending' and payment.get('mp_payment_id') and 'created_at' in payment:
        created_at = datetime.fromisoformat(payment['created_at'])
        expiration_time = created_at + timedelta(minutes=10)
        current_time = datetime.now()
        
        # Se ainda não expirou
        if current_time < expiration_time:
            minutes_left = int((expiration_time - current_time).total_seconds() / 60)
            seconds_left = int((expiration_time - current_time).total_seconds() % 60)
            
            expiration_info = f"\n⏰ *Tempo restante para pagamento: {minutes_left}min {seconds_left}s* ⏰\n"
        else:
            expiration_info = "\n⏰ *Este pagamento expirou!* ⏰\nCrie um novo pagamento.\n"
    
    if payment['status'] == 'pending':
        payment_msg += (
            f"Por favor, complete as informações de pagamento.\n"
            f"Clique em 'Continuar Pagamento' para prosseguir.{expiration_info}"
        )
    elif payment['status'] == 'pending_approval':
        payment_msg += (
            f"Seu pagamento está aguardando aprovação do administrador.\n"
            f"Você receberá uma notificação assim que for processado."
        )
    
    # Create keyboard
    keyboard = types.InlineKeyboardMarkup(row_width=1)
    
    if payment['status'] == 'pending':
        # Verificar o tipo de pagamento
        if payment.get('mp_payment_id'):
            # Pagamento via Mercado Pago
            keyboard.add(
                types.InlineKeyboardButton("📱 Continuar com PIX Mercado Pago", callback_data=f"pay_pix_mp_{payment_id}"),
                types.InlineKeyboardButton("↩️ Usar PIX Manual", callback_data=f"pay_pix_manual_{payment_id}"),
                types.InlineKeyboardButton("❌ Cancelar Pagamento", callback_data=f"cancel_payment_{payment_id}")
            )
        else:
            # Pagamento manual
            keyboard.add(
                types.InlineKeyboardButton("✅ Continuar Pagamento", callback_data=f"continue_payment_{payment_id}"),
                types.InlineKeyboardButton("❌ Cancelar Pagamento", callback_data=f"cancel_payment_{payment_id}")
            )
    elif payment['status'] == 'pending_approval':
        keyboard.add(
            types.InlineKeyboardButton("❌ Cancelar Pagamento", callback_data=f"cancel_payment_{payment_id}")
        )
    
    keyboard.add(types.InlineKeyboardButton("🔙 Voltar", callback_data="start"))
    
    # Edit message
    bot.edit_message_text(
        payment_msg,
        call.message.chat.id,
        call.message.message_id,
        reply_markup=keyboard,
        parse_mode="Markdown"
    )

def get_payment_status_text(status):
    status_map = {
        'pending': 'Pendente',
        'pending_approval': 'Aguardando Aprovação',
        'approved': 'Aprovado',
        'completed': 'Concluído',
        'rejected': 'Rejeitado',
        'cancelled': 'Cancelado'
    }
    return status_map.get(status, status)

# Continue payment
@bot.callback_query_handler(func=lambda call: call.data.startswith("continue_payment_"))
def continue_payment(call):
    payment_id = call.data.split("_")[2]
    payment = get_payment(payment_id)
    
    if not payment:
        bot.answer_callback_query(call.id, "Pagamento não encontrado!")
        return
    
    # Ask for payer name
    payment_msg = (
        f"💰 *Continuar Pagamento* 💰\n\n"
        f"Por favor, informe seu Nome Completo ou CNPJ:"
    )
    
    # Edit message
    bot.edit_message_text(
        payment_msg,
        call.message.chat.id,
        call.message.message_id,
        parse_mode="Markdown"
    )
    
    # Register next step
    bot.register_next_step_handler(call.message, process_payer_name, payment_id)

# Support
@bot.callback_query_handler(func=lambda call: call.data == "support")
def support(call):
    support_msg = (
        f"💬 *Suporte UniTV* 💬\n\n"
        f"Se você precisa de ajuda ou tem alguma dúvida, entre em contato com nosso suporte:"
    )
    
    keyboard = types.InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        types.InlineKeyboardButton("📞 Falar com o Suporte", url=f"https://t.me/ADMIN_USERNAME"),
        types.InlineKeyboardButton("🔙 Voltar", callback_data="start")
    )
    
    bot.edit_message_text(
        support_msg,
        call.message.chat.id,
        call.message.message_id,
        reply_markup=keyboard,
        parse_mode="Markdown"
    )

# Referral program
@bot.callback_query_handler(func=lambda call: call.data == "referral_program")
def referral_program(call):
    user_id = call.from_user.id
    user = get_user(user_id)
    
    # Get referral rewards info
    bot_config = read_json_file(BOT_CONFIG_FILE)
    referrer_discount = bot_config['referral_rewards']['referrer_discount']
    referred_discount = bot_config['referral_rewards']['referred_discount']
    free_month_after = bot_config['referral_rewards']['free_month_after_referrals']
    
    referral_msg = (
        f"🔗 *Programa de Indicação UniTV* 🔗\n\n"
        f"Indique seus amigos e ganhe recompensas!\n\n"
        f"*Como funciona:*\n"
        f"1. Compartilhe seu link de indicação com amigos\n"
        f"2. Quando seu amigo se cadastrar usando seu link e fizer a primeira compra, "
        f"você ganhará {referrer_discount}% de desconto na sua próxima renovação\n"
        f"3. Seu amigo também ganhará {referred_discount}% de desconto na segunda compra dele\n"
        f"4. A cada {free_month_after} indicações bem-sucedidas, você ganha um plano de 30 dias GRÁTIS!\n\n"
    )
    
    if user:
        referral_link = f"https://t.me/UniTV_Bot?start={user_id}"
        referral_msg += (
            f"*Seu link de indicação:*\n"
            f"`{referral_link}`\n\n"
            f"*Estatísticas:*\n"
            f"Pessoas indicadas: {len(user.get('referrals', []))}\n"
            f"Indicações bem-sucedidas: {user.get('successful_referrals', 0)}\n"
        )
        
        if user.get('successful_referrals', 0) > 0:
            referral_msg += f"Você já ganhou {user.get('successful_referrals', 0) // free_month_after} plano(s) grátis!\n"
    
    keyboard = types.InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        types.InlineKeyboardButton("📤 Compartilhar Link", switch_inline_query=f"Assine UniTV com meu link de indicação e ganhe {referred_discount}% de desconto na segunda compra!"),
        types.InlineKeyboardButton("🔙 Voltar", callback_data="start")
    )
    
    bot.edit_message_text(
        referral_msg,
        call.message.chat.id,
        call.message.message_id,
        reply_markup=keyboard,
        parse_mode="Markdown"
    )

# Admin commands
@bot.message_handler(commands=['addlogin'])
def add_login_command(message):
    # Check if admin
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "⛔ Comando exclusivo para administradores.")
        return
    
    # Extract login info from command
    args = message.text.split(' ', 1)
    
    if len(args) < 2:
        # Show instructions
        bot.reply_to(message, 
            "ℹ️ *Como adicionar logins:*\n\n"
            "Use o comando assim:\n"
            "`/addlogin email:senha plano`\n\n"
            "*Planos disponíveis:*\n"
            "• `30_dias` - Plano de 30 dias\n"
            "• `6_meses` - Plano de 6 meses\n"
            "• `1_ano` - Plano de 1 ano\n\n"
            "*Exemplo:*\n"
            "`/addlogin usuario@unitv.com:senha123 30_dias`",
            parse_mode="Markdown"
        )
        return
    
    # Parse login info
    login_info_parts = args[1].strip().split(' ')
    
    if len(login_info_parts) < 2:
        bot.reply_to(message, "❌ Formato incorreto. Use: `/addlogin email:senha plano`", parse_mode="Markdown")
        return
    
    login_data = login_info_parts[0]
    plan_type = login_info_parts[1]
    
    # Validate plan type
    plan_map = {
        '30_dias': '30_days',
        '6_meses': '6_months',
        '1_ano': '1_year',
        '30_days': '30_days',
        '6_months': '6_months',
        '1_year': '1_year'
    }
    
    if plan_type in plan_map:
        plan_type = plan_map[plan_type]
    
    if plan_type not in PLANS:
        bot.reply_to(message, 
            "❌ Plano inválido. Planos disponíveis:\n"
            "• `30_dias` ou `30_days` - Plano de 30 dias\n"
            "• `6_meses` ou `6_months` - Plano de 6 meses\n"
            "• `1_ano` ou `1_year` - Plano de 1 ano",
            parse_mode="Markdown"
        )
        return
    
    # Add login
    if add_login(plan_type, login_data):
        bot.reply_to(message, 
            f"✅ Login adicionado com sucesso!\n\n"
            f"Login: `{login_data}`\n"
            f"Plano: {PLANS[plan_type]['name']}",
            parse_mode="Markdown"
        )
        
        # Check if there are users waiting for logins
        check_waiting_users_for_login(plan_type)
        
        # If sales were suspended, check if we should resume
        bot_config = read_json_file(BOT_CONFIG_FILE)
        if not bot_config.get('sales_enabled', True):
            resume_sales()
            bot.send_message(
                ADMIN_ID,
                "✅ Vendas retomadas automaticamente após adição de novos logins!",
                parse_mode="Markdown"
            )
    else:
        bot.reply_to(message, "❌ Erro ao adicionar login.")

def check_waiting_users_for_login(plan_type):
    payments = read_json_file(PAYMENTS_FILE)
    waiting_users = []
    
    for payment_id, payment in payments.items():
        if payment['status'] == 'approved' and not payment['login_delivered'] and payment['plan_type'] == plan_type:
            waiting_users.append(payment)
    
    if waiting_users:
        for payment in waiting_users:
            user_id = payment['user_id']
            payment_id = payment['payment_id']
            
            # Try to assign login
            assigned_login = assign_login_to_user(user_id, plan_type, payment_id)
            
            if assigned_login:
                bot.send_message(
                    user_id,
                    f"🎉 *Seu login UniTV está pronto!* 🎉\n\n"
                    f"Login: `{assigned_login}`\n\n"
                    f"Seu plano expira em {PLANS[plan_type]['duration_days']} dias.\n"
                    f"Aproveite sua assinatura UniTV! 📺✨",
                    parse_mode="Markdown"
                )
                
                bot.send_message(
                    ADMIN_ID,
                    f"✅ Login enviado automaticamente para o usuário ID: {user_id}\n"
                    f"Plano: {PLANS[plan_type]['name']}"
                )
                
                # If coupon was used, mark it as used
                if payment.get('coupon_code'):
                    use_coupon(payment['coupon_code'], user_id)

@bot.message_handler(commands=['payments'])
def payments_command(message):
    # Check if admin
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "⛔ Comando exclusivo para administradores.")
        return
    
    # Get pending payments
    pending_approvals = get_pending_approvals()
    
    if not pending_approvals:
        bot.reply_to(message, "✅ Não há pagamentos pendentes de aprovação.")
        return
    
    # Create message
    payments_msg = f"💰 *Pagamentos Pendentes ({len(pending_approvals)})* 💰\n\n"
    
    for i, payment in enumerate(pending_approvals, 1):
        payments_msg += (
            f"*{i}. ID:* {payment['payment_id'][:8]}...\n"
            f"*Usuário:* {payment['user_id']}\n"
            f"*Plano:* {PLANS[payment['plan_type']]['name']}\n"
            f"*Valor:* {format_currency(payment['amount'])}\n"
            f"*Nome do Pagador:* {payment['payer_name']}\n"
            f"*Data:* {datetime.fromisoformat(payment['created_at']).strftime('%d/%m/%Y %H:%M')}\n\n"
        )
    
    bot.reply_to(message, payments_msg, parse_mode="Markdown")

@bot.message_handler(commands=['suspendvendas', 'suspendvendas'])
def suspend_sales_command(message):
    # Check if admin
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "⛔ Comando exclusivo para administradores.")
        return
    
    # Suspend sales
    suspend_sales()
    
    bot.reply_to(message, 
        "🛑 *Vendas Suspensas* 🛑\n\n"
        "As vendas foram suspensas temporariamente.\n"
        "Use /retomarsales para retomar as vendas quando desejar.",
        parse_mode="Markdown"
    )

@bot.message_handler(commands=['retomarsales', 'resumevendas'])
def resume_sales_command(message):
    # Check if admin
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "⛔ Comando exclusivo para administradores.")
        return
    
    # Resume sales
    resume_sales()
    
    bot.reply_to(message, 
        "✅ *Vendas Retomadas* ✅\n\n"
        "As vendas foram retomadas com sucesso.",
        parse_mode="Markdown"
    )

@bot.message_handler(commands=['criar_cupom'])
def create_coupon_command(message):
    # Check if admin
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "⛔ Comando exclusivo para administradores.")
        return
    
    # Start coupon creation wizard
    coupon_msg = (
        "🎟️ *Vamos criar um novo cupom!* 🎟️\n\n"
        "Deseja prosseguir?"
    )
    
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        types.InlineKeyboardButton("✅ Sim", callback_data="criar_cupom_sim"),
        types.InlineKeyboardButton("❌ Não", callback_data="criar_cupom_nao")
    )
    
    bot.reply_to(
        message,
        coupon_msg,
        reply_markup=keyboard,
        parse_mode="Markdown"
    )

@bot.callback_query_handler(func=lambda call: call.data == "criar_cupom_sim")
def create_coupon_step1(call):
    # Check if admin
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "⛔ Apenas administradores podem criar cupons!")
        return
    
    coupon_msg = (
        "🎟️ *Criar Novo Cupom - Passo 1/7* 🎟️\n\n"
        "Digite o código do cupom (Ex: VERAO20):"
    )
    
    bot.edit_message_text(
        coupon_msg,
        call.message.chat.id,
        call.message.message_id,
        parse_mode="Markdown"
    )
    
    bot.register_next_step_handler(call.message, process_coupon_code_step)

@bot.callback_query_handler(func=lambda call: call.data == "criar_cupom_nao")
def cancel_coupon_creation(call):
    bot.edit_message_text(
        "🎟️ *Criação de Cupom Cancelada* 🎟️\n\n"
        "A criação do cupom foi cancelada.",
        call.message.chat.id,
        call.message.message_id,
        parse_mode="Markdown"
    )

def process_coupon_code_step(message):
    # Check if admin
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "⛔ Comando exclusivo para administradores.")
        return
    
    coupon_code = message.text.strip().upper()
    
    # Validate coupon code
    if not coupon_code or len(coupon_code) < 3:
        bot.reply_to(message, "❌ Código de cupom muito curto. Deve ter pelo menos 3 caracteres.")
        bot.register_next_step_handler(message, process_coupon_code_step)
        return
    
    # Check if coupon already exists
    bot_config = read_json_file(BOT_CONFIG_FILE)
    if 'coupons' in bot_config and coupon_code in bot_config['coupons']:
        bot.reply_to(message, "❌ Este código de cupom já existe. Por favor, escolha outro código.")
        bot.register_next_step_handler(message, process_coupon_code_step)
        return
    
    # Store coupon code in context
    coupon_context = {'code': coupon_code}
    
    # Go to next step
    coupon_msg = (
        f"🎟️ *Criar Novo Cupom - Passo 2/7* 🎟️\n\n"
        f"Código: {coupon_code}\n\n"
        f"Escolha o tipo de desconto:"
    )
    
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        types.InlineKeyboardButton("% Porcentagem", callback_data=f"criar_cupom_tipo_percentage_{coupon_code}"),
        types.InlineKeyboardButton("R$ Fixo", callback_data=f"criar_cupom_tipo_fixed_{coupon_code}")
    )
    
    bot.reply_to(
        message,
        coupon_msg,
        reply_markup=keyboard,
        parse_mode="Markdown"
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith("criar_cupom_tipo_"))
def create_coupon_step3(call):
    # Check if admin
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "⛔ Apenas administradores podem criar cupons!")
        return
    
    # Parse callback data
    data_parts = call.data.split("_")
    discount_type = data_parts[3]
    coupon_code = data_parts[4]
    
    # Store discount type in context
    coupon_context = {'code': coupon_code, 'discount_type': discount_type}
    
    # Prepare message based on discount type
    if discount_type == 'percentage':
        value_msg = "Digite o valor do desconto percentual (Ex: 10 para 10%):"
    else:
        value_msg = "Digite o valor do desconto fixo em reais (Ex: 5 para R$ 5,00):"
    
    coupon_msg = (
        f"🎟️ *Criar Novo Cupom - Passo 3/7* 🎟️\n\n"
        f"Código: {coupon_code}\n"
        f"Tipo: {'Porcentagem' if discount_type == 'percentage' else 'Valor Fixo'}\n\n"
        f"{value_msg}"
    )
    
    bot.edit_message_text(
        coupon_msg,
        call.message.chat.id,
        call.message.message_id,
        parse_mode="Markdown"
    )
    
    # Register next step
    bot.register_next_step_handler(
        call.message, 
        process_discount_value_step, 
        coupon_code, 
        discount_type
    )

def process_discount_value_step(message, coupon_code, discount_type):
    # Check if admin
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "⛔ Comando exclusivo para administradores.")
        return
    
    # Validate discount value
    try:
        discount_value = float(message.text.strip())
        
        if discount_value <= 0:
            raise ValueError("Valor deve ser positivo")
        
        if discount_type == 'percentage' and discount_value >= 100:
            bot.reply_to(message, "❌ Desconto percentual deve ser menor que 100%. Digite um valor entre 1 e 99:")
            bot.register_next_step_handler(message, process_discount_value_step, coupon_code, discount_type)
            return
    except:
        bot.reply_to(message, "❌ Valor inválido. Digite apenas números (Ex: 10):")
        bot.register_next_step_handler(message, process_discount_value_step, coupon_code, discount_type)
        return
    
    # Store discount value in context
    coupon_context = {
        'code': coupon_code, 
        'discount_type': discount_type,
        'discount_value': discount_value
    }
    
    # Go to next step
    coupon_msg = (
        f"🎟️ *Criar Novo Cupom - Passo 4/7* 🎟️\n\n"
        f"Código: {coupon_code}\n"
        f"Tipo: {'Porcentagem' if discount_type == 'percentage' else 'Valor Fixo'}\n"
        f"Valor: {discount_value}{'%' if discount_type == 'percentage' else ''}\n\n"
        f"Escolha a data de validade:"
    )
    
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        types.InlineKeyboardButton("📅 Hoje + 7 dias", callback_data=f"criar_cupom_validade_7_{coupon_code}_{discount_type}_{discount_value}"),
        types.InlineKeyboardButton("📅 Hoje + 15 dias", callback_data=f"criar_cupom_validade_15_{coupon_code}_{discount_type}_{discount_value}"),
        types.InlineKeyboardButton("📅 Hoje + 30 dias", callback_data=f"criar_cupom_validade_30_{coupon_code}_{discount_type}_{discount_value}"),
        types.InlineKeyboardButton("🗓️ Escolher Data", callback_data=f"criar_cupom_validade_escolher_{coupon_code}_{discount_type}_{discount_value}")
    )
    
    bot.reply_to(
        message,
        coupon_msg,
        reply_markup=keyboard,
        parse_mode="Markdown"
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith("criar_cupom_validade_"))
def create_coupon_step5(call):
    # Check if admin
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "⛔ Apenas administradores podem criar cupons!")
        return
    
    # Parse callback data
    data_parts = call.data.split("_")
    validity_option = data_parts[3]
    coupon_code = data_parts[4]
    discount_type = data_parts[5]
    discount_value = float(data_parts[6])
    
    # Calculate expiration date
    if validity_option.isdigit():
        days = int(validity_option)
        expiration_date = (datetime.now() + timedelta(days=days)).isoformat()
        
        # Continue to next step
        process_expiration_date(
            call.message, 
            coupon_code, 
            discount_type, 
            discount_value, 
            expiration_date,
            is_callback=True,
            call_id=call.id
        )
    elif validity_option == 'escolher':
        # Ask for custom date
        coupon_msg = (
            f"🎟️ *Criar Novo Cupom - Passo 4/7* 🎟️\n\n"
            f"Código: {coupon_code}\n"
            f"Tipo: {'Porcentagem' if discount_type == 'percentage' else 'Valor Fixo'}\n"
            f"Valor: {discount_value}{'%' if discount_type == 'percentage' else ''}\n\n"
            f"Digite a data de validade no formato DD/MM/AAAA:"
        )
        
        bot.edit_message_text(
            coupon_msg,
            call.message.chat.id,
            call.message.message_id,
            parse_mode="Markdown"
        )
        
        # Register next step
        bot.register_next_step_handler(
            call.message, 
            process_custom_expiration_date, 
            coupon_code, 
            discount_type,
            discount_value
        )

def process_custom_expiration_date(message, coupon_code, discount_type, discount_value):
    # Check if admin
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "⛔ Comando exclusivo para administradores.")
        return
    
    # Validate date format
    date_str = message.text.strip()
    try:
        date_parts = date_str.split('/')
        if len(date_parts) != 3:
            raise ValueError("Invalid format")
        
        day = int(date_parts[0])
        month = int(date_parts[1])
        year = int(date_parts[2])
        
        expiration_date = datetime(year, month, day).isoformat()
        
        # Check if date is in the future
        if datetime.fromisoformat(expiration_date) <= datetime.now():
            bot.reply_to(message, "❌ A data de validade deve ser no futuro. Digite novamente (DD/MM/AAAA):")
            bot.register_next_step_handler(message, process_custom_expiration_date, coupon_code, discount_type, discount_value)
            return
    except:
        bot.reply_to(message, "❌ Formato de data inválido. Use DD/MM/AAAA (Ex: 31/12/2023):")
        bot.register_next_step_handler(message, process_custom_expiration_date, coupon_code, discount_type, discount_value)
        return
    
    # Continue to next step
    process_expiration_date(message, coupon_code, discount_type, discount_value, expiration_date)

def process_expiration_date(message, coupon_code, discount_type, discount_value, expiration_date, is_callback=False, call_id=None):
    # Create coupon context
    coupon_context = {
        'code': coupon_code,
        'discount_type': discount_type,
        'discount_value': discount_value,
        'expiration_date': expiration_date
    }
    
    # Format expiration date for display
    expiration_display = datetime.fromisoformat(expiration_date).strftime('%d/%m/%Y')
    
    # Go to next step
    coupon_msg = (
        f"🎟️ *Criar Novo Cupom - Passo 5/7* 🎟️\n\n"
        f"Código: {coupon_code}\n"
        f"Tipo: {'Porcentagem' if discount_type == 'percentage' else 'Valor Fixo'}\n"
        f"Valor: {discount_value}{'%' if discount_type == 'percentage' else ''}\n"
        f"Validade: {expiration_display}\n\n"
        f"Defina o número máximo de usos:"
    )
    
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        types.InlineKeyboardButton("♾️ Ilimitado", callback_data=f"criar_cupom_usos_-1_{coupon_code}_{discount_type}_{discount_value}_{expiration_date}"),
        types.InlineKeyboardButton("10", callback_data=f"criar_cupom_usos_10_{coupon_code}_{discount_type}_{discount_value}_{expiration_date}"),
        types.InlineKeyboardButton("50", callback_data=f"criar_cupom_usos_50_{coupon_code}_{discount_type}_{discount_value}_{expiration_date}"),
        types.InlineKeyboardButton("100", callback_data=f"criar_cupom_usos_100_{coupon_code}_{discount_type}_{discount_value}_{expiration_date}"),
        types.InlineKeyboardButton("🔢 Outro Valor", callback_data=f"criar_cupom_usos_outro_{coupon_code}_{discount_type}_{discount_value}_{expiration_date}")
    )
    
    if is_callback:
        bot.edit_message_text(
            coupon_msg,
            message.chat.id,
            message.message_id,
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        if call_id:
            bot.answer_callback_query(call_id)
    else:
        bot.reply_to(
            message,
            coupon_msg,
            reply_markup=keyboard,
            parse_mode="Markdown"
        )

@bot.callback_query_handler(func=lambda call: call.data.startswith("criar_cupom_usos_"))
def create_coupon_step6(call):
    # Check if admin
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "⛔ Apenas administradores podem criar cupons!")
        return
    
    # Parse callback data
    data_parts = call.data.split("_")
    max_uses_option = data_parts[3]
    coupon_code = data_parts[4]
    discount_type = data_parts[5]
    discount_value = float(data_parts[6])
    expiration_date = data_parts[7]
    
    if max_uses_option == 'outro':
        # Ask for custom max uses
        coupon_msg = (
            f"🎟️ *Criar Novo Cupom - Passo 5/7* 🎟️\n\n"
            f"Código: {coupon_code}\n"
            f"Tipo: {'Porcentagem' if discount_type == 'percentage' else 'Valor Fixo'}\n"
            f"Valor: {discount_value}{'%' if discount_type == 'percentage' else ''}\n"
            f"Validade: {datetime.fromisoformat(expiration_date).strftime('%d/%m/%Y')}\n\n"
            f"Digite o número máximo de usos (número inteiro):"
        )
        
        bot.edit_message_text(
            coupon_msg,
            call.message.chat.id,
            call.message.message_id,
            parse_mode="Markdown"
        )
        
        # Register next step
        bot.register_next_step_handler(
            call.message, 
            process_custom_max_uses, 
            coupon_code, 
            discount_type,
            discount_value,
            expiration_date
        )
    else:
        # Use predefined value
        max_uses = int(max_uses_option)
        
        # Continue to next step
        process_max_uses(
            call.message, 
            coupon_code, 
            discount_type, 
            discount_value, 
            expiration_date,
            max_uses,
            is_callback=True,
            call_id=call.id
        )

def process_custom_max_uses(message, coupon_code, discount_type, discount_value, expiration_date):
    # Check if admin
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "⛔ Comando exclusivo para administradores.")
        return
    
    # Validate max uses
    try:
        max_uses = int(message.text.strip())
        
        if max_uses < 1:
            bot.reply_to(message, "❌ O número máximo de usos deve ser pelo menos 1. Digite novamente:")
            bot.register_next_step_handler(message, process_custom_max_uses, coupon_code, discount_type, discount_value, expiration_date)
            return
    except:
        bot.reply_to(message, "❌ Valor inválido. Digite um número inteiro (Ex: 25):")
        bot.register_next_step_handler(message, process_custom_max_uses, coupon_code, discount_type, discount_value, expiration_date)
        return
    
    # Continue to next step
    process_max_uses(message, coupon_code, discount_type, discount_value, expiration_date, max_uses)

def process_max_uses(message, coupon_code, discount_type, discount_value, expiration_date, max_uses, is_callback=False, call_id=None):
    # Create coupon context
    coupon_context = {
        'code': coupon_code,
        'discount_type': discount_type,
        'discount_value': discount_value,
        'expiration_date': expiration_date,
        'max_uses': max_uses
    }
    
    # Format max uses for display
    max_uses_display = "Ilimitado" if max_uses == -1 else str(max_uses)
    
    # Go to next step
    coupon_msg = (
        f"🎟️ *Criar Novo Cupom - Passo 6/7* 🎟️\n\n"
        f"Código: {coupon_code}\n"
        f"Tipo: {'Porcentagem' if discount_type == 'percentage' else 'Valor Fixo'}\n"
        f"Valor: {discount_value}{'%' if discount_type == 'percentage' else ''}\n"
        f"Validade: {datetime.fromisoformat(expiration_date).strftime('%d/%m/%Y')}\n"
        f"Máximo de usos: {max_uses_display}\n\n"
        f"Valor mínimo de compra para aplicar o cupom:"
    )
    
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        types.InlineKeyboardButton("❌ Nenhum", callback_data=f"criar_cupom_minimo_0_{coupon_code}_{discount_type}_{discount_value}_{expiration_date}_{max_uses}"),
        types.InlineKeyboardButton("R$ 20,00", callback_data=f"criar_cupom_minimo_20_{coupon_code}_{discount_type}_{discount_value}_{expiration_date}_{max_uses}"),
        types.InlineKeyboardButton("R$ 50,00", callback_data=f"criar_cupom_minimo_50_{coupon_code}_{discount_type}_{discount_value}_{expiration_date}_{max_uses}"),
        types.InlineKeyboardButton("R$ 100,00", callback_data=f"criar_cupom_minimo_100_{coupon_code}_{discount_type}_{discount_value}_{expiration_date}_{max_uses}"),
        types.InlineKeyboardButton("🔢 Outro Valor", callback_data=f"criar_cupom_minimo_outro_{coupon_code}_{discount_type}_{discount_value}_{expiration_date}_{max_uses}")
    )
    
    if is_callback:
        bot.edit_message_text(
            coupon_msg,
            message.chat.id,
            message.message_id,
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        if call_id:
            bot.answer_callback_query(call_id)
    else:
        bot.reply_to(
            message,
            coupon_msg,
            reply_markup=keyboard,
            parse_mode="Markdown"
        )

@bot.callback_query_handler(func=lambda call: call.data.startswith("criar_cupom_minimo_"))
def create_coupon_step7(call):
    # Check if admin
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "⛔ Apenas administradores podem criar cupons!")
        return
    
    # Parse callback data
    data_parts = call.data.split("_")
    min_purchase_option = data_parts[3]
    coupon_code = data_parts[4]
    discount_type = data_parts[5]
    discount_value = float(data_parts[6])
    expiration_date = data_parts[7]
    max_uses = int(data_parts[8])
    
    if min_purchase_option == 'outro':
        # Ask for custom min purchase
        coupon_msg = (
            f"🎟️ *Criar Novo Cupom - Passo 6/7* 🎟️\n\n"
            f"Código: {coupon_code}\n"
            f"Tipo: {'Porcentagem' if discount_type == 'percentage' else 'Valor Fixo'}\n"
            f"Valor: {discount_value}{'%' if discount_type == 'percentage' else ''}\n"
            f"Validade: {datetime.fromisoformat(expiration_date).strftime('%d/%m/%Y')}\n"
            f"Máximo de usos: {max_uses if max_uses != -1 else 'Ilimitado'}\n\n"
            f"Digite o valor mínimo de compra (apenas números, Ex: 35.90):"
        )
        
        bot.edit_message_text(
            coupon_msg,
            call.message.chat.id,
            call.message.message_id,
            parse_mode="Markdown"
        )
        
        # Register next step
        bot.register_next_step_handler(
            call.message, 
            process_custom_min_purchase, 
            coupon_code, 
            discount_type,
            discount_value,
            expiration_date,
            max_uses
        )
    else:
        # Use predefined value
        min_purchase = float(min_purchase_option)
        
        # Continue to next step
        process_min_purchase(
            call.message, 
            coupon_code, 
            discount_type, 
            discount_value, 
            expiration_date,
            max_uses,
            min_purchase,
            is_callback=True,
            call_id=call.id
        )

def process_custom_min_purchase(message, coupon_code, discount_type, discount_value, expiration_date, max_uses):
    # Check if admin
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "⛔ Comando exclusivo para administradores.")
        return
    
    # Validate min purchase
    try:
        min_purchase = float(message.text.strip().replace(',', '.'))
        
        if min_purchase < 0:
            bot.reply_to(message, "❌ O valor mínimo não pode ser negativo. Digite novamente:")
            bot.register_next_step_handler(message, process_custom_min_purchase, coupon_code, discount_type, discount_value, expiration_date, max_uses)
            return
    except:
        bot.reply_to(message, "❌ Valor inválido. Digite um número (Ex: 35.90):")
        bot.register_next_step_handler(message, process_custom_min_purchase, coupon_code, discount_type, discount_value, expiration_date, max_uses)
        return
    
    # Continue to next step
    process_min_purchase(message, coupon_code, discount_type, discount_value, expiration_date, max_uses, min_purchase)

def process_min_purchase(message, coupon_code, discount_type, discount_value, expiration_date, max_uses, min_purchase, is_callback=False, call_id=None):
    # Create coupon context
    coupon_context = {
        'code': coupon_code,
        'discount_type': discount_type,
        'discount_value': discount_value,
        'expiration_date': expiration_date,
        'max_uses': max_uses,
        'min_purchase': min_purchase
    }
    
    # Format min purchase for display
    min_purchase_display = "Nenhum" if min_purchase == 0 else format_currency(min_purchase)
    
    # Go to next step
    coupon_msg = (
        f"🎟️ *Criar Novo Cupom - Passo 7/7* 🎟️\n\n"
        f"Código: {coupon_code}\n"
        f"Tipo: {'Porcentagem' if discount_type == 'percentage' else 'Valor Fixo'}\n"
        f"Valor: {discount_value}{'%' if discount_type == 'percentage' else ''}\n"
        f"Validade: {datetime.fromisoformat(expiration_date).strftime('%d/%m/%Y')}\n"
        f"Máximo de usos: {max_uses if max_uses != -1 else 'Ilimitado'}\n"
        f"Valor mínimo: {min_purchase_display}\n\n"
        f"Selecione os planos onde o cupom será aplicável:"
    )
    
    keyboard = types.InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        types.InlineKeyboardButton("✅ Todos", callback_data=f"criar_cupom_planos_todos_{coupon_code}_{discount_type}_{discount_value}_{expiration_date}_{max_uses}_{min_purchase}"),
        types.InlineKeyboardButton("✅ 30 Dias", callback_data=f"criar_cupom_planos_30_days_{coupon_code}_{discount_type}_{discount_value}_{expiration_date}_{max_uses}_{min_purchase}"),
        types.InlineKeyboardButton("✅ 6 Meses", callback_data=f"criar_cupom_planos_6_months_{coupon_code}_{discount_type}_{discount_value}_{expiration_date}_{max_uses}_{min_purchase}"),
        types.InlineKeyboardButton("✅ 1 Ano", callback_data=f"criar_cupom_planos_1_year_{coupon_code}_{discount_type}_{discount_value}_{expiration_date}_{max_uses}_{min_purchase}")
    )
    
    if is_callback:
        bot.edit_message_text(
            coupon_msg,
            message.chat.id,
            message.message_id,
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        if call_id:
            bot.answer_callback_query(call_id)
    else:
        bot.reply_to(
            message,
            coupon_msg,
            reply_markup=keyboard,
            parse_mode="Markdown"
        )

@bot.callback_query_handler(func=lambda call: call.data.startswith("criar_cupom_planos_"))
def create_coupon_final(call):
    # Check if admin
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "⛔ Apenas administradores podem criar cupons!")
        return
    
    # Parse callback data
    data_parts = call.data.split("_")
    plan_option = data_parts[3]
    coupon_code = data_parts[4]
    discount_type = data_parts[5]
    discount_value = float(data_parts[6])
    expiration_date = data_parts[7]
    max_uses = int(data_parts[8])
    min_purchase = float(data_parts[9])
    
    # Determine applicable plans
    if plan_option == 'todos':
        applicable_plans = ['all']
    else:
        applicable_plans = [plan_option]
    
    # Create the coupon
    success, message_text = add_coupon(
        coupon_code,
        discount_type,
        discount_value,
        expiration_date,
        max_uses,
        min_purchase,
        applicable_plans
    )
    
    if success:
        # Show success message
        coupon_msg = (
            f"🎉 *Cupom Criado com Sucesso!* 🎉\n\n"
            f"Código: {coupon_code}\n"
            f"Tipo: {'Porcentagem' if discount_type == 'percentage' else 'Valor Fixo'}\n"
            f"Valor: {discount_value}{'%' if discount_type == 'percentage' else ''}\n"
            f"Validade: {datetime.fromisoformat(expiration_date).strftime('%d/%m/%Y')}\n"
            f"Máximo de usos: {max_uses if max_uses != -1 else 'Ilimitado'}\n"
            f"Valor mínimo: {format_currency(min_purchase) if min_purchase > 0 else 'Nenhum'}\n"
            f"Planos aplicáveis: {', '.join(applicable_plans)}"
        )
        
        bot.edit_message_text(
            coupon_msg,
            call.message.chat.id,
            call.message.message_id,
            parse_mode="Markdown"
        )
    else:
        # Show error message
        bot.edit_message_text(
            f"❌ *Erro ao Criar Cupom* ❌\n\n{message_text}",
            call.message.chat.id,
            call.message.message_id,
            parse_mode="Markdown"
        )

@bot.message_handler(commands=['listar_cupons'])
def list_coupons_command(message):
    # Check if admin
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "⛔ Comando exclusivo para administradores.")
        return
    
    # Get coupons
    bot_config = read_json_file(BOT_CONFIG_FILE)
    coupons = bot_config.get('coupons', {})
    
    if not coupons:
        bot.reply_to(message, "ℹ️ Não há cupons cadastrados.")
        return
    
    # Create message
    coupons_msg = f"🎟️ *Cupons Ativos ({len(coupons)})* 🎟️\n\n"
    
    for code, coupon in coupons.items():
        expiration_date = datetime.fromisoformat(coupon['expiration_date']).strftime('%d/%m/%Y') if coupon['expiration_date'] else "Sem validade"
        max_uses = "Ilimitado" if coupon['max_uses'] == -1 else f"{coupon['uses']}/{coupon['max_uses']}"
        
        if coupon['discount_type'] == 'percentage':
            discount = f"{coupon['discount_value']}%"
        else:
            discount = format_currency(coupon['discount_value'])
        
        coupons_msg += (
            f"*Código:* {code}\n"
            f"*Desconto:* {discount}\n"
            f"*Validade:* {expiration_date}\n"
            f"*Usos:* {max_uses}\n"
            f"*Valor mínimo:* {format_currency(coupon['min_purchase']) if coupon['min_purchase'] > 0 else 'Nenhum'}\n"
            f"*Planos:* {', '.join(coupon['applicable_plans'])}\n\n"
        )
    
    bot.reply_to(message, coupons_msg, parse_mode="Markdown")

@bot.message_handler(commands=['excluir_cupom'])
def delete_coupon_command(message):
    # Check if admin
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "⛔ Comando exclusivo para administradores.")
        return
    
    # Get coupons
    bot_config = read_json_file(BOT_CONFIG_FILE)
    coupons = bot_config.get('coupons', {})
    
    if not coupons:
        bot.reply_to(message, "ℹ️ Não há cupons cadastrados para excluir.")
        return
    
    args = message.text.split(' ', 1)
    
    if len(args) > 1:
        # Direct deletion with code provided
        coupon_code = args[1].strip().upper()
        
        if coupon_code in coupons:
            if delete_coupon(coupon_code):
                bot.reply_to(message, f"✅ Cupom {coupon_code} excluído com sucesso!")
            else:
                bot.reply_to(message, f"❌ Erro ao excluir cupom {coupon_code}.")
        else:
            bot.reply_to(message, f"❌ Cupom {coupon_code} não encontrado.")
    else:
        # Show list of coupons to delete
        coupon_msg = "🗑️ *Excluir Cupom* 🗑️\n\nSelecione o cupom que deseja excluir:"
        
        keyboard = types.InlineKeyboardMarkup(row_width=1)
        
        for code in coupons.keys():
            keyboard.add(
                types.InlineKeyboardButton(code, callback_data=f"excluir_cupom_{code}")
            )
        
        keyboard.add(
            types.InlineKeyboardButton("❌ Cancelar", callback_data="excluir_cupom_cancelar")
        )
        
        bot.reply_to(
            message,
            coupon_msg,
            reply_markup=keyboard,
            parse_mode="Markdown"
        )

@bot.callback_query_handler(func=lambda call: call.data.startswith("excluir_cupom_"))
def delete_coupon_callback(call):
    # Check if admin
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "⛔ Apenas administradores podem excluir cupons!")
        return
    
    # Parse callback data
    data_parts = call.data.split("_")
    
    if data_parts[2] == 'cancelar':
        bot.edit_message_text(
            "🗑️ *Exclusão de Cupom Cancelada* 🗑️\n\n"
            "A exclusão do cupom foi cancelada.",
            call.message.chat.id,
            call.message.message_id,
            parse_mode="Markdown"
        )
        return
    
    coupon_code = data_parts[2]
    
    # Ask for confirmation
    confirm_msg = (
        f"🗑️ *Confirmar Exclusão* 🗑️\n\n"
        f"Tem certeza que deseja excluir o cupom {coupon_code}?"
    )
    
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        types.InlineKeyboardButton("✅ Sim", callback_data=f"confirmar_excluir_cupom_{coupon_code}"),
        types.InlineKeyboardButton("❌ Não", callback_data="excluir_cupom_cancelar")
    )
    
    bot.edit_message_text(
        confirm_msg,
        call.message.chat.id,
        call.message.message_id,
        reply_markup=keyboard,
        parse_mode="Markdown"
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith("confirmar_excluir_cupom_"))
def confirm_delete_coupon(call):
    # Check if admin
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "⛔ Apenas administradores podem excluir cupons!")
        return
    
    coupon_code = call.data.split("_")[3]
    
    if delete_coupon(coupon_code):
        bot.edit_message_text(
            f"✅ *Cupom Excluído* ✅\n\n"
            f"O cupom {coupon_code} foi excluído com sucesso!",
            call.message.chat.id,
            call.message.message_id,
            parse_mode="Markdown"
        )
    else:
        bot.edit_message_text(
            f"❌ *Erro ao Excluir Cupom* ❌\n\n"
            f"Ocorreu um erro ao excluir o cupom {coupon_code}.",
            call.message.chat.id,
            call.message.message_id,
            parse_mode="Markdown"
        )

# Admin login command - generates access code for the admin panel
@bot.message_handler(commands=['admin_login'])
def admin_login_command(message):
    user_id = message.from_user.id
    
    # Check if user is an admin or allowed user
    if not is_admin_telegram_id(user_id) and not is_allowed_telegram_id(user_id):
        bot.reply_to(
            message,
            "⛔ Você não tem permissão para acessar o painel administrativo."
        )
        return
    
    try:
        # Generate an access code (valid for 24 hours)
        access_code = generate_access_code(user_id, expiration_hours=24)
        
        # Get the host from environment or use a default
        base_url = os.environ.get('HOST_URL', '')
        login_url = f"{base_url}/login"
        
        # Send access code to user and guarda o ID da mensagem
        reply_msg = bot.reply_to(
            message,
            f"🔐 *Acesso ao Painel Administrativo* 🔐\n\n"
            f"Seu código de acesso é:\n\n"
            f"`{access_code}`\n\n"
            f"Este código é válido por 24 horas e pode ser usado apenas uma vez.\n\n"
            f"Para fazer login, acesse: {login_url}\n"
            f"E insira seu ID do Telegram ({user_id}) e o código de acesso acima.\n\n"
            f"⚠️ *Importante*: Guarde este código ou salve esta mensagem para utilizá-lo quando necessário.",
            parse_mode="Markdown"
        )
        
        # Salva o ID da mensagem para poder editá-la depois
        # Quando o código for utilizado, esta mensagem será atualizada
        auth_data = read_json_file(AUTH_FILE)
        if 'access_codes' in auth_data and access_code in auth_data['access_codes']:
            auth_data['access_codes'][access_code]['message_id'] = reply_msg.message_id
            write_json_file(AUTH_FILE, auth_data)
    except Exception as e:
        logger.error(f"Error generating access code: {e}")
        bot.reply_to(
            message, 
            "❌ Erro ao gerar código de acesso. Tente novamente."
        )

# Admin commands to manage allowed users
@bot.message_handler(commands=['add_admin'])
def add_admin_command(message):
    user_id = message.from_user.id
    
    # Only existing admin can add new admins
    if not is_admin_telegram_id(user_id):
        bot.reply_to(
            message,
            "⛔ Apenas administradores podem adicionar novos administradores."
        )
        return
    
    # Check if there's an ID in the message
    args = message.text.split()
    if len(args) != 2 or not args[1].isdigit():
        bot.reply_to(
            message,
            "❌ Uso incorreto. Envie `/add_admin ID_DO_TELEGRAM` para adicionar um novo administrador.",
            parse_mode="Markdown"
        )
        return
    
    new_admin_id = args[1]
    
    # Add user to the allowed list
    auth_data = read_json_file(AUTH_FILE)
    
    if 'admin_telegram_ids' not in auth_data:
        auth_data['admin_telegram_ids'] = []
    
    if str(new_admin_id) not in auth_data['admin_telegram_ids']:
        auth_data['admin_telegram_ids'].append(str(new_admin_id))
        write_json_file(AUTH_FILE, auth_data)
        
        bot.reply_to(
            message,
            f"✅ Administrador (ID: {new_admin_id}) adicionado com sucesso!"
        )
        
        # Notify the new admin
        try:
            bot.send_message(
                new_admin_id,
                f"🎉 Você agora é um administrador do sistema UniTV!\n\n"
                f"Use o comando /admin_login para acessar o painel administrativo."
            )
        except Exception as e:
            logger.error(f"Failed to notify new admin: {e}")
    else:
        bot.reply_to(
            message,
            f"⚠️ Este usuário (ID: {new_admin_id}) já é um administrador."
        )

# Add allowed user (not admin)
@bot.message_handler(commands=['add_user'])
def add_allowed_user_command(message):
    user_id = message.from_user.id
    
    # Only existing admin can add new allowed users
    if not is_admin_telegram_id(user_id):
        bot.reply_to(
            message,
            "⛔ Apenas administradores podem adicionar novos usuários permitidos."
        )
        return
    
    # Check if there's an ID in the message
    args = message.text.split()
    if len(args) != 2 or not args[1].isdigit():
        bot.reply_to(
            message,
            "❌ Uso incorreto. Envie `/add_user ID_DO_TELEGRAM` para adicionar um novo usuário permitido.",
            parse_mode="Markdown"
        )
        return
    
    new_user_id = args[1]
    
    # Add user to the allowed list
    if add_allowed_telegram_id(new_user_id):
        bot.reply_to(
            message,
            f"✅ Usuário (ID: {new_user_id}) adicionado com sucesso à lista de usuários permitidos!"
        )
        
        # Notify the new user
        try:
            bot.send_message(
                new_user_id,
                f"🎉 Você agora tem acesso ao painel administrativo do sistema UniTV!\n\n"
                f"Use o comando /admin_login para acessar."
            )
        except Exception as e:
            logger.error(f"Failed to notify new allowed user: {e}")
    else:
        bot.reply_to(
            message,
            f"⚠️ Este usuário (ID: {new_user_id}) já está na lista de usuários permitidos."
        )

# Back to start
# Gerenciamento de sorteios (admin)
@bot.callback_query_handler(func=lambda call: call.data == "admin_giveaways")
def admin_giveaways_menu(call):
    user_id = str(call.from_user.id)
    
    # Verificar se o usuário é admin
    if not is_admin_telegram_id(user_id):
        bot.answer_callback_query(call.id, "Acesso negado. Este recurso é exclusivo para administradores.")
        return
    
    # Criar teclado com opções
    keyboard = types.InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        types.InlineKeyboardButton("🆕 Criar Novo Sorteio", callback_data="create_giveaway"),
        types.InlineKeyboardButton("📋 Listar Sorteios Ativos", callback_data="list_giveaways"),
        types.InlineKeyboardButton("🔙 Voltar", callback_data="start")
    )
    
    # Atualizar mensagem
    bot.edit_message_text(
        "🎰 *Gerenciamento de Sorteios* 🎰\n\n"
        "Escolha uma opção para gerenciar os sorteios:",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=keyboard,
        parse_mode="Markdown"
    )

@bot.callback_query_handler(func=lambda call: call.data == "create_giveaway")
def create_giveaway_from_menu(call):
    # Simular a mensagem para a função existente
    fake_message = types.Message(
        message_id=call.message.message_id,
        from_user=call.from_user,
        date=None,
        chat=call.message.chat,
        content_type="text",
        options={},
        json_string=None
    )
    fake_message.text = "/giveaway create"
    
    # Chamar a função existente
    giveaway_create_step1(fake_message)

@bot.callback_query_handler(func=lambda call: call.data == "list_giveaways")
def list_giveaways_from_menu(call):
    # Obter sorteios ativos
    all_giveaways = get_giveaways_for_admin()
    active_giveaways = all_giveaways.get('active', {})
    
    if not active_giveaways:
        bot.edit_message_text(
            "❌ *Nenhum Sorteio Ativo* ❌\n\n"
            "Não há sorteios ativos no momento.",
            call.message.chat.id,
            call.message.message_id,
            parse_mode="Markdown",
            reply_markup=types.InlineKeyboardMarkup().add(
                types.InlineKeyboardButton("🔙 Voltar", callback_data="admin_giveaways")
            )
        )
        return
    
    # Criar mensagem com a lista de sorteios
    response = "🎰 *Sorteios Ativos* 🎰\n\n"
    
    # Criar teclado com botões para cada sorteio
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    
    for giveaway_id, giveaway in active_giveaways.items():
        if giveaway.get('status') == 'active':
            end_date = datetime.fromisoformat(giveaway["ends_at"])
            remaining_time = end_date - datetime.now()
            participants_count = len(giveaway.get('participants', {}))
            max_participants = giveaway.get('max_participants', 'Sem limite')
            
            response += f"ID: `{giveaway_id}`\n"
            response += f"Plano: *{giveaway['plan_name']}*\n"
            response += f"Ganhadores: {giveaway['winners_count']}\n"
            response += f"Participantes: {participants_count}/{max_participants}\n"
            response += f"Encerra em: {remaining_time.days}d {remaining_time.seconds//3600}h {(remaining_time.seconds%3600)//60}m\n"
            response += f"Status: {giveaway.get('status')}\n\n"
            
            # Adicionar botões para sortear e cancelar
            keyboard.add(
                types.InlineKeyboardButton(f"🎲 Sortear #{giveaway_id}", callback_data=f"menu_draw_{giveaway_id}"),
                types.InlineKeyboardButton(f"❌ Cancelar #{giveaway_id}", callback_data=f"menu_cancel_{giveaway_id}")
            )
    
    # Adicionar botão de voltar
    keyboard.add(
        types.InlineKeyboardButton("🔙 Voltar", callback_data="admin_giveaways")
    )
    
    # Atualizar mensagem
    bot.edit_message_text(
        response,
        call.message.chat.id,
        call.message.message_id,
        reply_markup=keyboard,
        parse_mode="Markdown"
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith("menu_draw_"))
def menu_draw_giveaway(call):
    giveaway_id = call.data.replace("menu_draw_", "")
    
    # Simular a mensagem para a função existente
    fake_message = types.Message(
        message_id=call.message.message_id,
        from_user=call.from_user,
        date=None,
        chat=call.message.chat,
        content_type="text",
        options={},
        json_string=None
    )
    fake_message.text = f"/giveaway draw {giveaway_id}"
    
    # Chamar a função existente
    giveaway_draw_command(fake_message, giveaway_id)
    
    # Voltar ao menu de sorteios após 3 segundos
    time.sleep(3)
    list_giveaways_from_menu(call)

@bot.callback_query_handler(func=lambda call: call.data.startswith("menu_cancel_"))
def menu_cancel_giveaway(call):
    giveaway_id = call.data.replace("menu_cancel_", "")
    
    # Confirmar antes de cancelar
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        types.InlineKeyboardButton("✅ Sim, Cancelar", callback_data=f"confirm_cancel_{giveaway_id}"),
        types.InlineKeyboardButton("❌ Não, Voltar", callback_data="list_giveaways")
    )
    
    bot.edit_message_text(
        f"⚠️ *Confirmar Cancelamento* ⚠️\n\n"
        f"Você tem certeza que deseja cancelar o sorteio #{giveaway_id}?\n\n"
        f"Esta ação não pode ser desfeita.",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=keyboard,
        parse_mode="Markdown"
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith("confirm_cancel_"))
def confirm_cancel_giveaway(call):
    giveaway_id = call.data.replace("confirm_cancel_", "")
    
    # Simular a mensagem para a função existente
    fake_message = types.Message(
        message_id=call.message.message_id,
        from_user=call.from_user,
        date=None,
        chat=call.message.chat,
        content_type="text",
        options={},
        json_string=None
    )
    fake_message.text = f"/giveaway cancel {giveaway_id}"
    
    # Chamar a função existente
    giveaway_cancel_command(fake_message, giveaway_id)
    
    # Voltar ao menu de sorteios após 3 segundos
    time.sleep(3)
    list_giveaways_from_menu(call)

@bot.callback_query_handler(func=lambda call: call.data == "start")
def back_to_start(call):
    user_id = call.from_user.id
    user = get_user(user_id)
    
    # Create welcome message
    welcome_msg = (
        f"👋 Olá {call.from_user.first_name}! Bem-vindo à loja da UniTV! 📺✨\n\n"
        f"Escolha uma das opções abaixo para continuar:"
    )
    
    # Create keyboard
    keyboard = types.InlineKeyboardMarkup(row_width=1)
    
    # Add buttons based on user status
    if user and user.get('has_active_plan'):
        plan_type = user.get('plan_type')
        expiration_date = datetime.fromisoformat(user.get('plan_expiration'))
        days_left = (expiration_date - datetime.now()).days
        
        # Add account info button
        keyboard.add(
            types.InlineKeyboardButton("📊 Minha Conta", callback_data="my_account")
        )
        
        # Add renew button if less than 10 days left
        if days_left <= 10:
            keyboard.add(
                types.InlineKeyboardButton("🔄 Renovar Assinatura", callback_data="show_plans")
            )
    else:
        # Check if sales are enabled
        if sales_enabled():
            keyboard.add(
                types.InlineKeyboardButton("🛒 Ver Planos", callback_data="show_plans")
            )
        else:
            welcome_msg += "\n\n⚠️ *As vendas estão temporariamente suspensas devido à alta demanda.* ⚠️"
    
    # Adicionar botão de sorteios ativos para todos os usuários
    active_giveaways = get_active_giveaways()
    if active_giveaways:
        keyboard.add(
            types.InlineKeyboardButton("🎁 Sorteios Ativos", callback_data="view_active_giveaways")
        )
    
    # Add support button
    keyboard.add(
        types.InlineKeyboardButton("💬 Suporte", callback_data="support"),
        types.InlineKeyboardButton("🔗 Programa de Indicação", callback_data="referral_program")
    )
    
    # Add giveaway button for admins
    if is_admin_telegram_id(str(call.from_user.id)):
        keyboard.add(
            types.InlineKeyboardButton("🎰 Gerenciar Sorteios", callback_data="admin_giveaways")
        )
    
    # Edit the message instead of sending new
    try:
        bot.edit_message_text(
            welcome_msg,
            call.message.chat.id,
            call.message.message_id,
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Error editing message: {e}")
        # Fallback to sending a new message if edit fails
        bot.send_message(
            call.message.chat.id,
            welcome_msg,
            reply_markup=keyboard,
            parse_mode="Markdown"
        )

# Comandos para gerenciar sorteios (admin)
@bot.message_handler(commands=['giveaway'])
def giveaway_command(message):
    """Comando de gerenciamento de sorteios para administradores"""
    user_id = str(message.from_user.id)
    
    # Verificar se o usuário é admin
    if not is_admin_telegram_id(user_id):
        bot.reply_to(
            message, 
            "⛔ Acesso negado. Este comando é exclusivo para administradores."
        )
        return
    
    args = message.text.split(maxsplit=1)
    
    # Se não houver argumentos, mostrar ajuda
    if len(args) == 1:
        bot.reply_to(
            message,
            "🎰 *Comandos de Sorteio* 🎰\n\n"
            "/giveaway create - Criar um novo sorteio\n"
            "/giveaway list - Listar sorteios ativos\n"
            "/giveaway draw <id> - Sortear ganhadores de um sorteio\n"
            "/giveaway cancel <id> - Cancelar um sorteio\n"
            "/giveaway help - Mostrar esta ajuda",
            parse_mode="Markdown"
        )
        return
    
    # Analisar subcomando
    subcommand = args[1].split()
    
    if subcommand[0] == "create":
        giveaway_create_step1(message)
    elif subcommand[0] == "list":
        giveaway_list_command(message)
    elif subcommand[0] == "draw" and len(subcommand) > 1:
        giveaway_draw_command(message, subcommand[1])
    elif subcommand[0] == "cancel" and len(subcommand) > 1:
        giveaway_cancel_command(message, subcommand[1])
    elif subcommand[0] == "help":
        bot.reply_to(
            message,
            "🎰 *Comandos de Sorteio* 🎰\n\n"
            "/giveaway create - Criar um novo sorteio\n"
            "/giveaway list - Listar sorteios ativos\n"
            "/giveaway draw <id> - Sortear ganhadores de um sorteio\n"
            "/giveaway cancel <id> - Cancelar um sorteio\n"
            "/giveaway help - Mostrar esta ajuda",
            parse_mode="Markdown"
        )
    else:
        bot.reply_to(
            message,
            "❌ Comando inválido. Use /giveaway help para ver os comandos disponíveis."
        )

def giveaway_create_step1(message):
    """Inicia o processo de criação de um sorteio - Passo 1: Selecionar plano"""
    keyboard = types.InlineKeyboardMarkup(row_width=1)
    
    # Adicionar botões para cada tipo de plano
    for plan_id, plan in PLANS.items():
        keyboard.add(
            types.InlineKeyboardButton(
                f"{plan['name']}",
                callback_data=f"create_giveaway_plan_{plan_id}"
            )
        )
    
    # Adicionar botão de cancelamento
    keyboard.add(
        types.InlineKeyboardButton("❌ Cancelar", callback_data="cancel_giveaway_creation")
    )
    
    # Enviar mensagem com seleção de plano
    bot.reply_to(
        message,
        "🎰 *Criação de Sorteio - Passo 1/4* 🎰\n\n"
        "Selecione o tipo de plano a ser sorteado:",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith("create_giveaway_plan_"))
def giveaway_create_step2(call):
    """Processo de criação de sorteio - Passo 2: Número de ganhadores"""
    plan_type = call.data.replace("create_giveaway_plan_", "")
    
    # Criar teclado com opções de número de ganhadores
    keyboard = types.InlineKeyboardMarkup(row_width=3)
    row1 = []
    row2 = []
    
    for i in range(1, 11):
        if i <= 5:
            row1.append(types.InlineKeyboardButton(str(i), callback_data=f"create_giveaway_winners_{plan_type}_{i}"))
        else:
            row2.append(types.InlineKeyboardButton(str(i), callback_data=f"create_giveaway_winners_{plan_type}_{i}"))
    
    keyboard.add(*row1)
    keyboard.add(*row2)
    
    # Adicionar botão de cancelamento
    keyboard.add(
        types.InlineKeyboardButton("❌ Cancelar", callback_data="cancel_giveaway_creation")
    )
    
    # Atualizar mensagem
    bot.edit_message_text(
        f"🎰 *Criação de Sorteio - Passo 2/4* 🎰\n\n"
        f"Plano selecionado: *{PLANS[plan_type]['name']}*\n\n"
        f"Selecione o número de ganhadores (1-10):",
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=keyboard,
        parse_mode="Markdown"
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith("create_giveaway_winners_"))
def giveaway_create_step3(call):
    """Processo de criação de sorteio - Passo 3: Duração do sorteio"""
    parts = call.data.split("_")
    plan_type = parts[3]
    winners_count = parts[4]
    
    # Criar teclado com opções de duração
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    
    durations = [
        ("1 hora", 1),
        ("6 horas", 6),
        ("12 horas", 12),
        ("24 horas", 24),
        ("48 horas", 48),
        ("72 horas", 72)
    ]
    
    buttons = []
    for label, hours in durations:
        buttons.append(types.InlineKeyboardButton(
            label, 
            callback_data=f"create_giveaway_duration_{plan_type}_{winners_count}_{hours}"
        ))
    
    keyboard.add(*buttons)
    
    # Adicionar botão de cancelamento
    keyboard.add(
        types.InlineKeyboardButton("❌ Cancelar", callback_data="cancel_giveaway_creation")
    )
    
    # Atualizar mensagem
    bot.edit_message_text(
        f"🎰 *Criação de Sorteio - Passo 3/4* 🎰\n\n"
        f"Plano: *{PLANS[plan_type]['name']}*\n"
        f"Ganhadores: *{winners_count}*\n\n"
        f"Selecione a duração do sorteio:",
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=keyboard,
        parse_mode="Markdown"
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith("create_giveaway_duration_"))
def giveaway_create_step4(call):
    """Processo de criação de sorteio - Passo 4: Limite de participantes (opcional)"""
    parts = call.data.split("_")
    plan_type = parts[3]
    winners_count = parts[4]
    duration_hours = parts[5]
    
    # Criar teclado com opções de limite de participantes
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    
    limits = [
        ("Sem limite", 0),
        ("10 participantes", 10),
        ("25 participantes", 25),
        ("50 participantes", 50),
        ("100 participantes", 100),
        ("200 participantes", 200)
    ]
    
    buttons = []
    for label, limit in limits:
        buttons.append(types.InlineKeyboardButton(
            label, 
            callback_data=f"create_giveaway_limit_{plan_type}_{winners_count}_{duration_hours}_{limit}"
        ))
    
    keyboard.add(*buttons)
    
    # Adicionar botão de cancelamento
    keyboard.add(
        types.InlineKeyboardButton("❌ Cancelar", callback_data="cancel_giveaway_creation")
    )
    
    # Atualizar mensagem
    bot.edit_message_text(
        f"🎰 *Criação de Sorteio - Passo 4/4* 🎰\n\n"
        f"Plano: *{PLANS[plan_type]['name']}*\n"
        f"Ganhadores: *{winners_count}*\n"
        f"Duração: *{duration_hours} horas*\n\n"
        f"Selecione o limite de participantes (opcional):",
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=keyboard,
        parse_mode="Markdown"
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith("create_giveaway_limit_"))
def giveaway_create_final(call):
    """Finaliza o processo de criação de sorteio"""
    parts = call.data.split("_")
    plan_type = parts[3]
    winners_count = int(parts[4])
    duration_hours = int(parts[5])
    max_participants = int(parts[6])
    
    # Converter 0 para None (sem limite)
    if max_participants == 0:
        max_participants = None
    
    # Criar sorteio
    admin_id = call.from_user.id
    giveaway_id = create_giveaway(admin_id, plan_type, winners_count, duration_hours, max_participants)
    
    if giveaway_id:
        # Criar botão para compartilhar o sorteio
        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(
            types.InlineKeyboardButton("📣 Anunciar Sorteio", callback_data=f"announce_giveaway_{giveaway_id}")
        )
        
        # Mostrar mensagem de sucesso
        bot.edit_message_text(
            f"✅ *Sorteio Criado com Sucesso!* ✅\n\n"
            f"ID do Sorteio: `{giveaway_id}`\n"
            f"Plano: *{PLANS[plan_type]['name']}*\n"
            f"Ganhadores: *{winners_count}*\n"
            f"Duração: *{duration_hours} horas*\n"
            f"Limite de Participantes: *{max_participants if max_participants else 'Sem limite'}*\n\n"
            f"Use o botão abaixo para anunciar o sorteio:",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
    else:
        # Mostrar mensagem de erro
        bot.edit_message_text(
            "❌ *Erro ao criar sorteio* ❌\n\n"
            "Não foi possível criar o sorteio. Por favor, tente novamente.",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            parse_mode="Markdown"
        )
        
@bot.callback_query_handler(func=lambda call: call.data.startswith("announce_giveaway_"))
def announce_giveaway(call):
    """Anuncia um sorteio para todos os usuários ativos"""
    giveaway_id = call.data.replace("announce_giveaway_", "")
    
    # Obter dados do sorteio
    success, user_ids, giveaway_data = notify_users_about_giveaway(giveaway_id)
    
    if not success or not giveaway_data:
        bot.answer_callback_query(
            call.id,
            "❌ Não foi possível anunciar o sorteio. Verifique se ele ainda está ativo.",
            show_alert=True
        )
        return
    
    # Informar ao admin que a notificação está sendo enviada
    bot.edit_message_text(
        f"📣 *Anunciando sorteio para {len(user_ids)} usuários...* 📣\n\n"
        f"ID do Sorteio: `{giveaway_id}`\n"
        f"Plano: *{giveaway_data['plan_name']}*\n"
        f"Ganhadores: *{giveaway_data['winners_count']}*\n"
        f"Duração: *{giveaway_data['duration_hours']} horas*\n"
        f"Limite de Participantes: *{giveaway_data['max_participants'] if giveaway_data['max_participants'] else 'Sem limite'}*\n\n"
        f"Os usuários estão sendo notificados...",
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        parse_mode="Markdown"
    )
    
    # Enviar notificação para todos os usuários na lista
    sent_count = 0
    for user_id in user_ids:
        try:
            # Criar teclado com botão para participar
            keyboard = types.InlineKeyboardMarkup()
            keyboard.add(
                types.InlineKeyboardButton(
                    "🎲 Participar do Sorteio", 
                    callback_data=f"join_giveaway_{giveaway_id}"
                )
            )
            
            # Calcular tempo restante
            ends_at = datetime.fromisoformat(giveaway_data['ends_at'])
            remaining = ends_at - datetime.now()
            remaining_hours = remaining.total_seconds() // 3600
            remaining_minutes = (remaining.total_seconds() % 3600) // 60
            
            # Enviar mensagem
            description = giveaway_data.get('description', '')
            description_text = f"\n\n{description}" if description else ""
            
            bot.send_message(
                user_id,
                f"🎰 *NOVO SORTEIO DISPONÍVEL!* 🎰\n\n"
                f"Prêmio: *{giveaway_data['plan_name']}*\n"
                f"Ganhadores: *{giveaway_data['winners_count']}*\n"
                f"Encerra em: *{int(remaining_hours)}h {int(remaining_minutes)}min*\n"
                f"Participantes: *0/{giveaway_data['max_participants'] if giveaway_data['max_participants'] else '∞'}*"
                f"{description_text}\n\n"
                f"Clique no botão abaixo para participar:",
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
            sent_count += 1
        except Exception as e:
            logger.error(f"Error sending giveaway notification to user {user_id}: {e}")
    
    # Atualizar mensagem com o resultado
    bot.edit_message_text(
        f"✅ *Sorteio anunciado com sucesso!* ✅\n\n"
        f"ID do Sorteio: `{giveaway_id}`\n"
        f"Plano: *{giveaway_data['plan_name']}*\n"
        f"Ganhadores: *{giveaway_data['winners_count']}*\n"
        f"Duração: *{giveaway_data['duration_hours']} horas*\n"
        f"Limite de Participantes: *{giveaway_data['max_participants'] if giveaway_data['max_participants'] else 'Sem limite'}*\n\n"
        f"Notificação enviada para *{sent_count}* de *{len(user_ids)}* usuários.",
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        parse_mode="Markdown"
    )

@bot.callback_query_handler(func=lambda call: call.data == "cancel_giveaway_creation")
def cancel_giveaway_creation(call):
    """Cancela o processo de criação de sorteio"""
    bot.edit_message_text(
        "⚠️ *Criação de Sorteio Cancelada* ⚠️",
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        parse_mode="Markdown"
    )



def giveaway_list_command(message):
    """Lista todos os sorteios ativos"""
    # Verificar se o usuário é admin
    user_id = str(message.from_user.id)
    if not is_admin_telegram_id(user_id):
        bot.reply_to(message, "⛔ Acesso negado. Este comando é exclusivo para administradores.")
        return
    
    # Obter sorteios ativos
    giveaways = get_giveaways_for_admin()
    
    if not giveaways:
        bot.reply_to(message, "❌ Não há sorteios ativos no momento.")
        return
    
    # Criar mensagem com a lista de sorteios
    response = "🎰 *Sorteios Ativos* 🎰\n\n"
    
    for giveaway_id, giveaway in giveaways.items():
        if giveaway['status'] == 'active':
            end_date = datetime.fromisoformat(giveaway["ends_at"])
            remaining_time = end_date - datetime.now()
            participants_count = len(giveaway.get('participants', {}))
            max_participants = giveaway.get('max_participants', 'Sem limite')
            
            response += f"ID: `{giveaway_id}`\n"
            response += f"Plano: *{giveaway['plan_name']}*\n"
            response += f"Ganhadores: {giveaway['winners_count']}\n"
            response += f"Participantes: {participants_count}/{max_participants}\n"
            response += f"Encerra em: {remaining_time.days}d {remaining_time.seconds//3600}h {(remaining_time.seconds%3600)//60}m\n"
            response += f"Status: {giveaway['status']}\n\n"
    
    bot.reply_to(message, response, parse_mode="Markdown")

def giveaway_draw_command(message, giveaway_id):
    """Comando para sortear ganhadores de um sorteio"""
    # Verificar se o usuário é admin
    user_id = str(message.from_user.id)
    if not is_admin_telegram_id(user_id):
        bot.reply_to(message, "⛔ Acesso negado. Este comando é exclusivo para administradores.")
        return
    
    # Verificar se o sorteio existe
    giveaway = get_giveaway(giveaway_id)
    if not giveaway:
        bot.reply_to(message, "❌ Sorteio não encontrado.")
        return
    
    # Verificar se o sorteio está ativo e não expirado
    if giveaway['status'] != 'active':
        if giveaway['status'] == 'pending_draw':
            # Realizar o sorteio normalmente - já expirou
            perform_draw(message, giveaway_id)
        else:
            bot.reply_to(message, f"❌ Não é possível sortear agora. Status atual do sorteio: {giveaway['status']}")
        return
    
    # Sorteio está ativo e ainda não expirou - pedir confirmação
    end_time = datetime.fromisoformat(giveaway["ends_at"])
    remaining_time = end_time - datetime.now()
    hours, remainder = divmod(remaining_time.seconds, 3600)
    minutes, _ = divmod(remainder, 60)
    
    # Criar botões de confirmação
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(
        types.InlineKeyboardButton("✅ Sim, sortear agora", callback_data=f"confirm_early_draw_{giveaway_id}"),
        types.InlineKeyboardButton("❌ Não, cancelar", callback_data="cancel_early_draw")
    )
    
    # Pedir confirmação
    participants_count = len(giveaway.get('participants', {}))
    bot.reply_to(
        message,
        f"⚠️ *ATENÇÃO: Sorteio Antecipado* ⚠️\n\n"
        f"Este sorteio ainda está ativo e terminaria em *{remaining_time.days}d {hours}h {minutes}m*.\n\n"
        f"Detalhes do sorteio:\n"
        f"ID: `{giveaway_id}`\n"
        f"Plano: *{giveaway['plan_name']}*\n"
        f"Participantes: *{participants_count}*\n\n"
        f"Tem certeza que deseja realizar o sorteio antecipadamente?",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith("confirm_early_draw_"))
def confirm_early_draw_callback(call):
    """Confirma o sorteio antecipado de um giveaway"""
    giveaway_id = call.data.replace("confirm_early_draw_", "")
    
    # Remover o teclado da mensagem original
    bot.edit_message_reply_markup(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=None
    )
    
    # Editar a mensagem original
    bot.edit_message_text(
        "✅ *Realizando sorteio antecipado...* ✅",
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        parse_mode="Markdown"
    )
    
    # Realizar o sorteio com o parâmetro force=True
    winners = draw_giveaway_winners(giveaway_id, force=True)
    
    # Responder ao callback
    if winners is None:
        bot.send_message(
            call.message.chat.id,
            "❌ Erro ao realizar o sorteio.",
            reply_to_message_id=call.message.message_id
        )
        return
    
    if len(winners) == 0:
        bot.send_message(
            call.message.chat.id,
            "⚠️ Não há participantes suficientes para realizar o sorteio.",
            reply_to_message_id=call.message.message_id
        )
        return
    
    # Obter detalhes do sorteio
    giveaway = get_giveaway(giveaway_id)
    
    # Enviar mensagem com os ganhadores
    response = f"🎉 *Sorteio #{giveaway_id} - Ganhadores* 🎉\n\n"
    response += f"Plano: *{giveaway['plan_name']}*\n"
    response += f"Total de participantes: {len(giveaway.get('participants', {}))}\n\n"
    response += f"*Ganhadores:*\n"
    
    for winner_id in winners:
        # Buscar informações do usuário (nome, username)
        participant = giveaway['participants'].get(winner_id, {})
        username = participant.get('username', 'N/A')
        first_name = participant.get('first_name', 'Usuário')
        response += f"- {first_name} (@{username}) - ID: `{winner_id}`\n"
    
    response += "\n⚠️ Cada ganhador tem 10 minutos para confirmar a vitória."
    
    bot.send_message(
        call.message.chat.id,
        response,
        parse_mode="Markdown"
    )
    
    # Notificar os ganhadores
    for winner_id in winners:
        try:
            # Criar botão de confirmação
            keyboard = types.InlineKeyboardMarkup()
            keyboard.add(
                types.InlineKeyboardButton(
                    "✅ Confirmar Participação", 
                    callback_data=f"confirm_giveaway_{giveaway_id}"
                )
            )
            
            # Enviar mensagem para o ganhador
            bot.send_message(
                winner_id,
                f"🎉 *PARABÉNS! Você foi sorteado!* 🎉\n\n"
                f"Você ganhou o seguinte plano no sorteio:\n"
                f"*{giveaway['plan_name']}*\n\n"
                f"⚠️ *ATENÇÃO*: Você tem 10 minutos para confirmar sua participação clicando no botão abaixo.\n"
                f"Caso contrário, um novo ganhador será sorteado.",
                parse_mode="Markdown",
                reply_markup=keyboard
            )
        except Exception as e:
            logger.error(f"Erro ao notificar ganhador {winner_id}: {e}")

@bot.callback_query_handler(func=lambda call: call.data == "cancel_early_draw")
def cancel_early_draw_callback(call):
    """Cancela o sorteio antecipado"""
    # Remover o teclado e atualizar a mensagem
    bot.edit_message_text(
        "❌ Sorteio antecipado cancelado.",
        chat_id=call.message.chat.id,
        message_id=call.message.message_id
    )
    
    # Responder ao callback
    bot.answer_callback_query(
        call.id,
        "Operação cancelada. O sorteio continuará normalmente até o final do prazo."
    )
    
def perform_draw(message, giveaway_id):
    """Função auxiliar para realizar o sorteio"""
    # Realizar o sorteio
    winners = draw_giveaway_winners(giveaway_id)
    
    if winners is None:
        bot.reply_to(
            message, 
            "❌ Não foi possível realizar o sorteio. Verifique se o sorteio existe e está ativo."
        )
        return
    
    if len(winners) == 0:
        bot.reply_to(
            message, 
            "⚠️ Não há participantes suficientes para realizar o sorteio."
        )
        return
    
    # Obter detalhes do sorteio
    giveaway = get_giveaway(giveaway_id)
    
    # Enviar mensagem com os ganhadores
    response = f"🎉 *Sorteio #{giveaway_id} - Ganhadores* 🎉\n\n"
    response += f"Plano: *{giveaway['plan_name']}*\n"
    response += f"Total de participantes: {len(giveaway.get('participants', {}))}\n\n"
    response += f"*Ganhadores:*\n"
    
    for winner_id in winners:
        # Buscar informações do usuário (nome, username)
        participant = giveaway['participants'].get(winner_id, {})
        username = participant.get('username', 'N/A')
        first_name = participant.get('first_name', 'Usuário')
        response += f"- {first_name} (@{username}) - ID: `{winner_id}`\n"
    
    response += "\n⚠️ Cada ganhador tem 10 minutos para confirmar a vitória."
    
    bot.reply_to(message, response, parse_mode="Markdown")
    
    # Notificar os ganhadores
    for winner_id in winners:
        try:
            # Criar botão de confirmação
            keyboard = types.InlineKeyboardMarkup()
            keyboard.add(
                types.InlineKeyboardButton(
                    "✅ Confirmar Participação", 
                    callback_data=f"confirm_giveaway_{giveaway_id}"
                )
            )
            
            # Enviar mensagem para o ganhador
            bot.send_message(
                winner_id,
                f"🎉 *PARABÉNS! Você foi sorteado!* 🎉\n\n"
                f"Você ganhou o seguinte plano no sorteio:\n"
                f"*{giveaway['plan_name']}*\n\n"
                f"⚠️ *ATENÇÃO*: Você tem 10 minutos para confirmar sua participação clicando no botão abaixo.\n"
                f"Caso contrário, um novo ganhador será sorteado.",
                parse_mode="Markdown",
                reply_markup=keyboard
            )
        except Exception as e:
            logger.error(f"Erro ao notificar ganhador {winner_id}: {e}")

def giveaway_cancel_command(message, giveaway_id):
    """Comando para cancelar um sorteio"""
    # Verificar se o usuário é admin
    user_id = str(message.from_user.id)
    if not is_admin_telegram_id(user_id):
        bot.reply_to(message, "⛔ Acesso negado. Este comando é exclusivo para administradores.")
        return
    
    # Cancelar o sorteio
    success = cancel_giveaway(giveaway_id, user_id)
    
    if success:
        bot.reply_to(
            message, 
            f"✅ Sorteio #{giveaway_id} cancelado com sucesso."
        )
    else:
        bot.reply_to(
            message, 
            "❌ Não foi possível cancelar o sorteio. Verifique se o sorteio existe e está ativo."
        )

# Comandos para usuários visualizarem sorteios ativos
@bot.callback_query_handler(func=lambda call: call.data == "view_active_giveaways")
def view_active_giveaways(call):
    """Permite que um usuário veja os sorteios ativos e participe"""
    user_id = call.from_user.id
    active_giveaways = get_active_giveaways()
    
    if not active_giveaways:
        bot.answer_callback_query(
            call.id, 
            "Não há sorteios ativos no momento.", 
            show_alert=True
        )
        # Voltar para o menu inicial
        back_to_start(call)
        return
    
    # Criar mensagem com a lista de sorteios
    response = "🎁 *Sorteios Ativos* 🎁\n\n" 
    response += "Escolha um sorteio para participar:\n\n"
    
    # Criar teclado com botões para cada sorteio
    keyboard = types.InlineKeyboardMarkup(row_width=1)
    
    for giveaway_id, giveaway in active_giveaways.items():
        if giveaway.get('status') == 'active':
            # Calcular tempo restante
            end_date = datetime.fromisoformat(giveaway["ends_at"])
            remaining_time = end_date - datetime.now()
            remaining_hours = remaining_time.total_seconds() / 3600
            remaining_minutes = (remaining_time.total_seconds() % 3600) / 60
            
            # Verificar se o sorteio tem limite de participantes
            participants_count = len(giveaway.get('participants', []))
            max_participants = giveaway.get('max_participants')
            participants_text = f"{participants_count}" 
            if max_participants:
                participants_text += f"/{max_participants}"
                
                # Verificar se já atingiu o limite
                if participants_count >= max_participants:
                    continue  # Pular este sorteio pois já está cheio
            else:
                participants_text += "/∞"
            
            # Adicionar botão para o sorteio
            plan_name = giveaway.get('plan_name', 'Desconhecido')
            keyboard.add(
                types.InlineKeyboardButton(
                    f"{plan_name} - {int(remaining_hours)}h {int(remaining_minutes)}min", 
                    callback_data=f"giveaway_details_{giveaway_id}"
                )
            )
    
    # Adicionar botão para voltar
    keyboard.add(
        types.InlineKeyboardButton("🔙 Voltar", callback_data="start")
    )
    
    # Verificar se há sorteios disponíveis
    if len(keyboard.keyboard) <= 1:  # Se só tiver o botão de voltar
        bot.answer_callback_query(
            call.id, 
            "Não há sorteios disponíveis ou todos já estão com limite de participantes atingido.", 
            show_alert=True
        )
        # Voltar para o menu inicial
        back_to_start(call)
        return
    
    # Editar a mensagem com a lista de sorteios
    bot.edit_message_text(
        response,
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=keyboard,
        parse_mode="Markdown"
    )

# Handler para exibir detalhes de um sorteio específico
@bot.callback_query_handler(func=lambda call: call.data.startswith("giveaway_details_"))
def view_giveaway_details(call):
    """Exibe detalhes de um sorteio específico e permite participar"""
    user_id = call.from_user.id
    giveaway_id = call.data.replace("giveaway_details_", "")
    
    giveaway = get_giveaway(giveaway_id)
    if not giveaway or giveaway.get('status') != 'active':
        bot.answer_callback_query(
            call.id, 
            "Este sorteio não está mais disponível.", 
            show_alert=True
        )
        view_active_giveaways(call)
        return
    
    # Calcular tempo restante
    end_date = datetime.fromisoformat(giveaway["ends_at"])
    remaining_time = end_date - datetime.now()
    remaining_hours = remaining_time.total_seconds() / 3600
    remaining_minutes = (remaining_time.total_seconds() % 3600) / 60
    
    # Verificar se o usuário já está participando
    user_is_participant = str(user_id) in giveaway.get('participants', [])
    
    # Preparar mensagem com detalhes do sorteio
    plan_name = giveaway.get('plan_name', 'Desconhecido')
    winners_count = giveaway.get('winners_count', 1)
    participants_count = len(giveaway.get('participants', []))
    max_participants = giveaway.get('max_participants')
    participants_text = f"{participants_count}"
    if max_participants:
        participants_text += f"/{max_participants}"
    else:
        participants_text += "/∞"
    
    message = (
        f"🎁 *Detalhes do Sorteio* 🎁\n\n"
        f"Prêmio: *{plan_name}*\n"
        f"Número de ganhadores: *{winners_count}*\n"
        f"Participantes atuais: *{participants_text}*\n"
        f"Tempo restante: *{int(remaining_hours)}h {int(remaining_minutes)}min*\n\n"
    )
    
    if user_is_participant:
        message += "✅ *Você já está participando deste sorteio!*\n\n"
        message += "Aguarde o sorteio acontecer no horário marcado. Boa sorte! 🍀"
    else:
        message += "Clique no botão abaixo para participar deste sorteio:"
    
    # Preparar teclado
    keyboard = types.InlineKeyboardMarkup(row_width=1)
    
    if not user_is_participant:
        keyboard.add(
            types.InlineKeyboardButton("🎯 Participar do Sorteio", callback_data=f"join_giveaway_{giveaway_id}")
        )
    
    keyboard.add(
        types.InlineKeyboardButton("🔙 Voltar aos Sorteios", callback_data="view_active_giveaways"),
        types.InlineKeyboardButton("🏠 Menu Principal", callback_data="start")
    )
    
    # Editar a mensagem com os detalhes do sorteio
    bot.edit_message_text(
        message,
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=keyboard,
        parse_mode="Markdown"
    )

# Comandos para usuários participarem dos sorteios
@bot.callback_query_handler(func=lambda call: call.data.startswith("join_giveaway_"))
def join_giveaway_callback(call):
    """Permite que um usuário participe de um sorteio"""
    user_id = str(call.from_user.id)
    giveaway_id = call.data.replace("join_giveaway_", "")
    
    # Verificar se o usuário existe
    user = get_user(user_id)
    if not user:
        # Criar o usuário se não existir
        user = create_user(
            user_id,
            call.from_user.username,
            call.from_user.first_name,
            call.from_user.last_name
        )
    
    # Adicionar o usuário como participante
    success, current, maximum = add_participant_to_giveaway(
        giveaway_id, 
        user_id, 
        call.from_user.username or "", 
        call.from_user.first_name or ""
    )
    
    if not success:
        bot.answer_callback_query(
            call.id, 
            "Não foi possível participar do sorteio. Ele pode ter sido encerrado ou você já está participando.", 
            show_alert=True
        )
        return
    
    # Atualizar o botão com o número atual de participantes
    keyboard = types.InlineKeyboardMarkup()
    button_text = f"🎲 Participar do Sorteio ({current}/{maximum if maximum else '∞'})"
    keyboard.add(
        types.InlineKeyboardButton(button_text, callback_data=f"join_giveaway_{giveaway_id}")
    )
    
    try:
        # Tentar atualizar a mensagem original
        bot.edit_message_reply_markup(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=keyboard
        )
    except Exception as e:
        logger.error(f"Erro ao atualizar botão de sorteio: {e}")
    
    # Notificar o usuário
    bot.answer_callback_query(
        call.id, 
        "✅ Você está participando do sorteio! Os vencedores serão anunciados quando o sorteio terminar.", 
        show_alert=True
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith("confirm_giveaway_"))
def confirm_giveaway_win_callback(call):
    """Confirma que um usuário aceitou o prêmio do sorteio"""
    user_id = str(call.from_user.id)
    giveaway_id = call.data.replace("confirm_giveaway_", "")
    
    # Confirmar a vitória
    success = confirm_giveaway_win(giveaway_id, user_id)
    
    if not success:
        bot.answer_callback_query(
            call.id, 
            "Não foi possível confirmar sua participação. O tempo limite pode ter expirado.", 
            show_alert=True
        )
        return
    
    # Notificar o usuário sobre o sucesso
    bot.edit_message_text(
        f"✅ *Sua vitória foi confirmada!* ✅\n\n"
        f"Um administrador entrará em contato para entregar seu prêmio.\n"
        f"Aguarde o contato e obrigado pela participação!",
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        parse_mode="Markdown"
    )
    
    # Notificar o administrador
    try:
        giveaway = get_giveaway(giveaway_id)
        if giveaway:
            admin_id = giveaway.get('admin_id')
            if admin_id:
                bot.send_message(
                    admin_id,
                    f"✅ *Confirmação de Vitória* ✅\n\n"
                    f"Sorteio: #{giveaway_id}\n"
                    f"Usuário: {call.from_user.first_name} (ID: {user_id})\n"
                    f"Plano: {giveaway['plan_name']}\n\n"
                    f"O ganhador confirmou a vitória e está aguardando o envio do login.",
                    parse_mode="Markdown"
                )
    except Exception as e:
        logger.error(f"Erro ao notificar administrador sobre confirmação: {e}")
    
    # Responder ao callback
    bot.answer_callback_query(
        call.id, 
        "✅ Confirmação recebida! Um administrador entrará em contato para entregar seu prêmio.", 
        show_alert=True
    )

# Track if the bot is already running, mas de uma forma menos restritiva
_bot_running = False

# Main function to start bot
def run_bot():
    global _bot_running
    
    # Se o bot já estiver executando, registramos o evento mas seguimos com
    # a inicialização. Isso permite que múltiplas chamadas da função não interrompam
    # o funcionamento do bot caso uma instância falhe.
    if _bot_running:
        logger.info("Bot may already be running in another thread/process")
    
    _bot_running = True
    logger.info("Starting Telegram bot...")
    
    # Corrigir pagamentos inconsistentes antes de iniciar o bot
    try:
        fixed_count = fix_inconsistent_payments()
        if fixed_count > 0:
            logger.info(f"Corrigidos {fixed_count} pagamentos inconsistentes na inicialização")
            msg = f"🔄 *Manutenção do Sistema* 🔄\n\n{fixed_count} pagamento(s) inconsistente(s) foram corrigidos automaticamente durante a inicialização."
            bot.send_message(ADMIN_ID, msg, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Erro ao corrigir pagamentos inconsistentes: {e}")
    
    # Iniciar tarefas em segundo plano
    start_background_tasks()
    
    # Primeiro, tentar limpar quaisquer atualizações pendentes
    # para evitar conflitos com outras instâncias
    try:
        bot.get_updates(offset=-1, timeout=1)
    except Exception as e:
        logger.warning(f"Error clearing pending updates: {e}")
    
    try:
        # O infinity_polling já inclui non_stop=True por padrão
        bot.infinity_polling(timeout=20, allowed_updates=None)
    except Exception as e:
        logger.error(f"Bot polling error: {e}")
    finally:
        _bot_running = False
        logger.info("Bot stopped running")

if __name__ == "__main__":
    run_bot()
