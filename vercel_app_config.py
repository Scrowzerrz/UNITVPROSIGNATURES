"""
Configurações específicas para o ambiente Vercel.
Este arquivo contém funções e configurações que são aplicadas
apenas quando o aplicativo está rodando no ambiente Vercel.
"""
import os
import logging
import secrets

logger = logging.getLogger(__name__)

def configure_app_for_vercel(app):
    """
    Configura a aplicação para o ambiente Vercel.
    
    Esta função adapta o aplicativo Flask para rodar no ambiente serverless
    do Vercel, desabilitando threads desnecessárias e configurando
    componentes para o modo serverless.
    
    Args:
        app: Aplicação Flask a ser configurada
    
    Returns:
        A mesma aplicação Flask, porém configurada para Vercel
    """
    logger.info("Configurando aplicativo para ambiente Vercel")
    
    # Desativar threads em segundo plano e processos de longa duração
    app.config['VERCEL_ENV'] = True
    app.config['DISABLE_BOT_THREADS'] = True
    
    # Gerar token para webhook se não existir
    if 'WEBHOOK_TOKEN' not in os.environ:
        # Gerar um token seguro para uso com o webhook
        webhook_token = secrets.token_hex(16)
        os.environ['WEBHOOK_TOKEN'] = webhook_token
        
        # Log para o administrador poder configurar o webhook
        logger.warning(f"WEBHOOK_TOKEN não encontrado no ambiente. Token temporário gerado: {webhook_token}")
        logger.warning("Para configurar o webhook do Telegram, use este comando:")
        bot_token = os.environ.get('TELEGRAM_BOT_TOKEN', 'SEU_BOT_TOKEN')
        vercel_url = os.environ.get('VERCEL_URL', 'seu-app.vercel.app')
        
        if vercel_url:
            webhook_url = f"https://{vercel_url}/api/telegram-webhook?token={webhook_token}"
            logger.warning(f"curl -X POST https://api.telegram.org/bot{bot_token}/setWebhook?url={webhook_url}")
    else:
        logger.info("WEBHOOK_TOKEN encontrado no ambiente. Pronto para receber updates do Telegram.")
    
    # Verificar variáveis de ambiente essenciais
    required_vars = ['SESSION_SECRET', 'TELEGRAM_BOT_TOKEN', 'ADMIN_ID']
    missing_vars = [var for var in required_vars if var not in os.environ]
    
    if missing_vars:
        vars_str = ', '.join(missing_vars)
        logger.warning(f"As seguintes variáveis de ambiente não foram encontradas: {vars_str}")
        logger.warning("Configure estas variáveis no painel do Vercel para garantir o funcionamento adequado do aplicativo.")
    
    # Configurar outras opções específicas para o Vercel
    app.config['PREFERRED_URL_SCHEME'] = 'https'  # Forçar URLs https
    app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024  # Limitar uploads a 5MB
    app.config['SERVER_NAME'] = os.environ.get('VERCEL_URL')  # Usar URL do Vercel se disponível
    
    # Inicializar estruturas de dados se necessário
    try:
        from config import init_json_files
        init_json_files()
        logger.info("Arquivos JSON inicializados")
    except Exception as e:
        logger.error(f"Erro ao inicializar arquivos JSON: {e}")
    
    # Configurações específicas para adaptação ao ambiente serverless
    # Desativar threads de fundo do bot
    try:
        import bot
        setattr(bot, '_bot_running', False)
        logger.info("Flag _bot_running configurada para False")
    except Exception as e:
        logger.error(f"Erro ao configurar bot: {e}")
    
    return app