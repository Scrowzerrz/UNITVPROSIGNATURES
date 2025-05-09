import logging
import uuid
from datetime import datetime
from config import TICKETS_FILE
from utils import read_json_file, write_json_file, get_user

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ====================================================
# Funções de gerenciamento de tickets de suporte
# ====================================================

def create_support_ticket(user_id, message_text, message_id=None):
    """
    Cria um novo ticket de suporte.
    
    Args:
        user_id (int): ID do usuário no Telegram
        message_text (str): Texto da mensagem inicial do ticket
        message_id (int, optional): ID da mensagem atual no Telegram, para referência
        
    Returns:
        str: ID do ticket criado ou None em caso de erro
    """
    try:
        tickets = read_json_file(TICKETS_FILE)
        
        # Gera um ID sequencial para o ticket
        ticket_id = str(tickets.get('current_id', 0) + 1)
        tickets['current_id'] = int(ticket_id)
        
        # Obter informações do usuário
        user = get_user(user_id)
        user_name = f"{user.get('first_name', '')} {user.get('last_name', '')}".strip() if user else f"User {user_id}"
        username = user.get('username', '') if user else ''
        
        # Cria o ticket
        now = datetime.now().isoformat()
        new_ticket = {
            'id': ticket_id,
            'user_id': user_id,
            'user_name': user_name,
            'username': username,
            'status': 'open',
            'created_at': now,
            'updated_at': now,
            'messages': [
                {
                    'id': str(uuid.uuid4()),
                    'from_id': user_id,
                    'from_type': 'user',
                    'text': message_text,
                    'timestamp': now,
                    'read': False
                }
            ],
            'admin_notified': False,
            'admin_replies': 0,
            'user_replies': 1,
            'message_tracking': {}  # Para rastrear IDs de mensagens do Telegram
        }
        
        # Se fornecido um message_id, salva para rastreamento
        if message_id:
            new_ticket['message_tracking']['user_main_message_id'] = message_id
        
        # Adiciona o ticket aos tickets ativos
        tickets['active'][ticket_id] = new_ticket
        
        # Salva os tickets
        write_json_file(TICKETS_FILE, tickets)
        
        return ticket_id
    except Exception as e:
        logger.error(f"Error creating support ticket: {e}")
        return None

def add_message_to_ticket(ticket_id, from_id, from_type, message_text, message_id=None):
    """
    Adiciona uma mensagem a um ticket existente.
    
    Args:
        ticket_id (str): ID do ticket
        from_id (int): ID de quem enviou a mensagem
        from_type (str): 'user' ou 'admin'
        message_text (str): Texto da mensagem
        message_id (int, optional): ID da mensagem no Telegram, para rastreamento
        
    Returns:
        bool: True se adicionado com sucesso, False caso contrário
    """
    try:
        tickets = read_json_file(TICKETS_FILE)
        
        # Verifica se o ticket existe
        if ticket_id not in tickets['active']:
            return False
        
        # Adiciona a mensagem
        now = datetime.now().isoformat()
        new_message = {
            'id': str(uuid.uuid4()),
            'from_id': from_id,
            'from_type': from_type,
            'text': message_text,
            'timestamp': now,
            'read': False
        }
        
        tickets['active'][ticket_id]['messages'].append(new_message)
        tickets['active'][ticket_id]['updated_at'] = now
        
        # Se não existir a estrutura de rastreamento de mensagens, cria-a
        if 'message_tracking' not in tickets['active'][ticket_id]:
            tickets['active'][ticket_id]['message_tracking'] = {}
        
        # Se fornecido um message_id, salva para rastreamento
        if message_id:
            key = f"{from_type}_message_id"
            tickets['active'][ticket_id]['message_tracking'][key] = message_id
        
        # Atualiza contadores
        if from_type == 'admin':
            tickets['active'][ticket_id]['admin_replies'] += 1
            # Quando admin responde, marca que foi notificado
            tickets['active'][ticket_id]['admin_notified'] = True
        else:
            tickets['active'][ticket_id]['user_replies'] += 1
            # Quando usuário responde, marca que admin não foi notificado
            tickets['active'][ticket_id]['admin_notified'] = False
        
        # Salva os tickets
        write_json_file(TICKETS_FILE, tickets)
        
        return True
    except Exception as e:
        logger.error(f"Error adding message to ticket: {e}")
        return False

def close_ticket(ticket_id, closed_by):
    """
    Fecha um ticket de suporte.
    
    Args:
        ticket_id (str): ID do ticket
        closed_by (str): 'user' ou 'admin'
        
    Returns:
        bool: True se fechado com sucesso, False caso contrário
    """
    try:
        tickets = read_json_file(TICKETS_FILE)
        
        # Verifica se o ticket existe
        if ticket_id not in tickets['active']:
            return False
        
        # Obtém o ticket e atualiza o status
        ticket = tickets['active'][ticket_id]
        ticket['status'] = 'closed'
        ticket['closed_at'] = datetime.now().isoformat()
        ticket['closed_by'] = closed_by
        
        # Move o ticket para a lista de tickets fechados
        tickets['closed'][ticket_id] = ticket
        del tickets['active'][ticket_id]
        
        # Salva os tickets
        write_json_file(TICKETS_FILE, tickets)
        
        return True
    except Exception as e:
        logger.error(f"Error closing ticket: {e}")
        return False

def reopen_ticket(ticket_id):
    """
    Reabre um ticket de suporte fechado.
    
    Args:
        ticket_id (str): ID do ticket
        
    Returns:
        bool: True se reaberto com sucesso, False caso contrário
    """
    try:
        tickets = read_json_file(TICKETS_FILE)
        
        # Verifica se o ticket existe na lista de tickets ativos
        if ticket_id in tickets['active']:
            # Se o ticket já está ativo, apenas verifica se está fechado
            if tickets['active'][ticket_id]['status'] == 'closed':
                tickets['active'][ticket_id]['status'] = 'open'
                tickets['active'][ticket_id].pop('closed_at', None)
                tickets['active'][ticket_id].pop('closed_by', None)
                tickets['active'][ticket_id]['updated_at'] = datetime.now().isoformat()
                write_json_file(TICKETS_FILE, tickets)
                return True
            return True  # Já está aberto
        
        # Verifica se o ticket existe nos fechados
        if 'closed' in tickets and ticket_id in tickets['closed']:
            # Obtém o ticket e atualiza o status
            ticket = tickets['closed'][ticket_id]
            ticket['status'] = 'open'
            ticket['updated_at'] = datetime.now().isoformat()
            
            # Remove campos de fechamento
            if 'closed_at' in ticket:
                del ticket['closed_at']
            if 'closed_by' in ticket:
                del ticket['closed_by']
            
            # Move o ticket para a lista de tickets ativos
            tickets['active'][ticket_id] = ticket
            del tickets['closed'][ticket_id]
            
            # Salva os tickets
            write_json_file(TICKETS_FILE, tickets)
            
            return True
        
        return False  # Ticket não encontrado
    except Exception as e:
        logger.error(f"Error reopening ticket: {e}")
        return False

def get_ticket(ticket_id):
    """
    Obtém informações de um ticket.
    
    Args:
        ticket_id (str): ID do ticket
        
    Returns:
        dict: Dados do ticket ou None se não encontrado
    """
    try:
        tickets = read_json_file(TICKETS_FILE)
        
        # Procura nos tickets ativos
        if ticket_id in tickets['active']:
            return tickets['active'][ticket_id]
        
        # Procura nos tickets fechados
        if ticket_id in tickets['closed']:
            return tickets['closed'][ticket_id]
        
        return None
    except Exception as e:
        logger.error(f"Error getting ticket: {e}")
        return None

def get_user_active_tickets(user_id):
    """
    Obtém todos os tickets ativos de um usuário.
    
    Args:
        user_id (int): ID do usuário no Telegram
        
    Returns:
        list: Lista de tickets ativos do usuário
    """
    try:
        tickets = read_json_file(TICKETS_FILE)
        
        user_tickets = []
        for ticket_id, ticket in tickets['active'].items():
            if str(ticket['user_id']) == str(user_id):
                user_tickets.append(ticket)
        
        return user_tickets
    except Exception as e:
        logger.error(f"Error getting user tickets: {e}")
        return []

def get_all_active_tickets():
    """
    Obtém todos os tickets ativos.
    
    Returns:
        dict: Dicionário de tickets ativos
    """
    try:
        tickets = read_json_file(TICKETS_FILE)
        
        # Verifica se a estrutura de tickets ativos existe e a inicializa se necessário
        if not tickets:
            tickets = {'active': {}, 'closed': {}, 'current_id': 0}
            write_json_file(TICKETS_FILE, tickets)
            
        # Garantir que a chave 'active' existe
        if 'active' not in tickets:
            tickets['active'] = {}
            write_json_file(TICKETS_FILE, tickets)
            
        return tickets.get('active', {})
    except Exception as e:
        logger.error(f"Error getting active tickets: {e}")
        return {}
        
def get_all_closed_tickets():
    """
    Obtém todos os tickets fechados/arquivados.
    
    Returns:
        dict: Dicionário de tickets fechados/arquivados
    """
    try:
        tickets = read_json_file(TICKETS_FILE)
        
        # Verifica se a estrutura de tickets fechados existe e a inicializa se necessário
        if not tickets:
            tickets = {'active': {}, 'closed': {}, 'current_id': 0}
            write_json_file(TICKETS_FILE, tickets)
            
        # Garantir que a chave 'closed' existe
        if 'closed' not in tickets:
            tickets['closed'] = {}
            write_json_file(TICKETS_FILE, tickets)
            
        return tickets.get('closed', {})
    except Exception as e:
        logger.error(f"Error getting closed tickets: {e}")
        return {}

def mark_ticket_messages_as_read(ticket_id, reader_type):
    """
    Marca todas as mensagens não lidas em um ticket como lidas para um determinado tipo de leitor.
    
    Args:
        ticket_id (str): ID do ticket
        reader_type (str): 'user' ou 'admin'
        
    Returns:
        bool: True se marcado com sucesso, False caso contrário
    """
    try:
        tickets = read_json_file(TICKETS_FILE)
        
        # Verifica se o ticket existe
        if ticket_id not in tickets['active']:
            return False
        
        # Marca mensagens como lidas
        for i, message in enumerate(tickets['active'][ticket_id]['messages']):
            # Só marca como lida se a mensagem não for do tipo do leitor
            # Ex: admin só marca como lidas mensagens do user e vice-versa
            if message['from_type'] != reader_type and not message['read']:
                tickets['active'][ticket_id]['messages'][i]['read'] = True
        
        # Se for admin lendo, marca que o admin foi notificado
        if reader_type == 'admin':
            tickets['active'][ticket_id]['admin_notified'] = True
        
        # Salva os tickets
        write_json_file(TICKETS_FILE, tickets)
        
        return True
    except Exception as e:
        logger.error(f"Error marking ticket messages as read: {e}")
        return False

def get_unread_ticket_count(reader_id, reader_type):
    """
    Obtém a contagem de tickets com mensagens não lidas.
    
    Args:
        reader_id (int): ID do leitor (usuário ou admin)
        reader_type (str): 'user' ou 'admin'
        
    Returns:
        int: Número de tickets com mensagens não lidas
    """
    try:
        tickets = read_json_file(TICKETS_FILE)
        
        unread_count = 0
        for ticket_id, ticket in tickets['active'].items():
            # Se for usuário, só conta tickets deste usuário
            if reader_type == 'user' and str(ticket['user_id']) != str(reader_id):
                continue
                
            for message in ticket['messages']:
                # Mensagens não lidas e que não são do tipo do leitor
                if not message['read'] and message['from_type'] != reader_type:
                    unread_count += 1
                    break
        
        return unread_count
    except Exception as e:
        logger.error(f"Error getting unread ticket count: {e}")
        return 0

def get_tickets_needing_admin_notification():
    """
    Obtém tickets que precisam de notificação para o admin.
    São tickets que foram criados/atualizados por usuários mas o admin ainda não foi notificado.
    
    Returns:
        list: Lista de tickets que precisam de notificação
    """
    try:
        tickets = read_json_file(TICKETS_FILE)
        
        need_notification = []
        for ticket_id, ticket in tickets['active'].items():
            if not ticket['admin_notified']:
                need_notification.append(ticket)
        
        return need_notification
    except Exception as e:
        logger.error(f"Error getting tickets needing admin notification: {e}")
        return []


def get_all_admin_ids():
    """
    Obtém uma lista de IDs de todos os administradores
    
    Returns:
        list: Lista com IDs dos administradores
    """
    from config import AUTH_FILE
    from utils import is_admin_telegram_id
    
    try:
        auth_data = read_json_file(AUTH_FILE)
        
        admin_ids = []
        
        # Adiciona administradores do arquivo de autenticação
        for admin_id in auth_data.get('admin_telegram_ids', []):
            admin_ids.append(admin_id)
        
        # Adiciona o admin principal do .env
        from config import ADMIN_ID
        if ADMIN_ID and ADMIN_ID not in admin_ids:
            admin_ids.append(ADMIN_ID)
            
        return admin_ids
    except Exception as e:
        logger.error(f"Error getting admin IDs: {e}")
        # Fallback para o admin principal
        from config import ADMIN_ID
        return [ADMIN_ID] if ADMIN_ID else []


def update_ticket_message_id(ticket_id, user_type, message_id):
    """
    Atualiza o ID da mensagem do Telegram para um determinado ticket.
    
    Args:
        ticket_id (str): ID do ticket
        user_type (str): 'user' ou 'admin'
        message_id (int): ID da mensagem no Telegram
        
    Returns:
        bool: True se atualizado com sucesso, False caso contrário
    """
    try:
        tickets = read_json_file(TICKETS_FILE)
        
        # Verifica se o ticket existe
        if ticket_id not in tickets['active']:
            return False
        
        # Certifica-se de que a estrutura de rastreamento existe
        if 'message_tracking' not in tickets['active'][ticket_id]:
            tickets['active'][ticket_id]['message_tracking'] = {}
        
        # Atualiza o ID da mensagem
        key = f"{user_type}_message_id"
        tickets['active'][ticket_id]['message_tracking'][key] = message_id
        
        # Salva os tickets
        write_json_file(TICKETS_FILE, tickets)
        
        return True
    except Exception as e:
        logger.error(f"Error updating ticket message ID: {e}")
        return False


def get_ticket_message_id(ticket_id, user_type):
    """
    Obtém o ID da mensagem do Telegram para um determinado ticket.
    
    Args:
        ticket_id (str): ID do ticket
        user_type (str): 'user' ou 'admin'
        
    Returns:
        int: ID da mensagem ou None se não encontrado
    """
    try:
        ticket = get_ticket(ticket_id)
        
        if not ticket or 'message_tracking' not in ticket:
            return None
        
        key = f"{user_type}_message_id"
        return ticket['message_tracking'].get(key)
    except Exception as e:
        logger.error(f"Error getting ticket message ID: {e}")
        return None


def notify_admins_about_ticket_reply(ticket_id, user_id, message_text):
    """
    Prepara as informações para notificar os administradores sobre uma nova resposta em um ticket
    
    Args:
        ticket_id (str): ID do ticket
        user_id (str): ID do usuário que respondeu
        message_text (str): Texto da mensagem
    
    Returns:
        dict: Informações para notificação
    """
    try:
        # Obter informações adicionais do ticket
        ticket = get_ticket(ticket_id)
        
        if not ticket:
            logger.error(f"Ticket {ticket_id} não encontrado ao tentar notificar admin")
            return None
            
        # Retorna as informações necessárias para notificação
        return {
            'ticket_id': ticket_id,
            'user_id': user_id,
            'user_name': ticket.get('user_name', f"User {user_id}"),
            'message': message_text,
            'ticket': ticket
        }
        
    except Exception as e:
        logger.error(f"Error preparing admin notification for ticket: {e}")
        return None