# Passos Simplificados para Deploy no Vercel

Este documento apresenta os passos essenciais para fazer o deploy da aplicação UniTV no Vercel, de forma simplificada.

## 1. Prepare seu código para o Vercel

Os seguintes arquivos já foram criados e configurados:

- `vercel.json` - Configuração principal com múltiplos pontos de entrada
- `api/serverless.py` - Handler serverless simplificado (funciona em /api/health e /api/status)
- `api/wsgi.py` - Adaptador WSGI para a aplicação Flask principal
- `vercel-requirements.txt` - Dependências
- `.vercelignore` - Arquivos a ignorar
- `vercel_app_config.py` - Configurações específicas
- `index.py` - Ponto de entrada

## 2. Crie uma conta no Vercel

Acesse [vercel.com](https://vercel.com) e crie uma conta caso ainda não tenha.

## 3. Publique seu código no GitHub

1. Crie um repositório no GitHub
2. Faça upload do código para o repositório

```bash
git init
git add .
git commit -m "Preparação para deploy no Vercel"
git remote add origin https://github.com/seu-usuario/unitv.git
git push -u origin main
```

## 4. Faça o deploy no Vercel

1. Acesse [vercel.com/new](https://vercel.com/new)
2. Importe seu repositório GitHub
3. Configure o projeto:
   - Framework: Selecione "Other"
   - Install Command: `pip install -r vercel-requirements.txt`
   - Output Directory: deixe em branco

## 5. Configure as variáveis de ambiente

No painel de configuração do projeto no Vercel, adicione:

- `SESSION_SECRET`: uma string segura aleatória
- `TELEGRAM_BOT_TOKEN`: seu token do bot Telegram
- `ADMIN_ID`: ID do Telegram do administrador principal
- Outras variáveis necessárias para o funcionamento da aplicação

## 6. Finalize o deploy

Clique no botão "Deploy" e aguarde o processo finalizar.

## 7. Ajustes após o deploy

### Bot Telegram

Devido à natureza serverless do Vercel, recomendamos:

1. Configure o bot para usar webhook ao invés de polling
2. OU hospede o bot em um serviço separado que suporte processos contínuos

### Armazenamento de dados

Como o sistema de arquivos no Vercel não é persistente entre requisições, considere:

1. Usar banco de dados como MongoDB Atlas, Firebase, ou PostgreSQL (Neon)
2. Adaptar o código para usar o armazenamento escolhido

## Mais informações

Consulte o arquivo `README-VERCEL.md` para instruções detalhadas e solução de problemas comuns.