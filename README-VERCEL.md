# Deployment do UniTV no Vercel

Este guia fornece instruções sobre como fazer o deployment da aplicação UniTV no Vercel.

## Pré-requisitos

1. Uma conta no [Vercel](https://vercel.com)
2. [Git](https://git-scm.com/downloads) instalado em seu computador
3. O código-fonte do projeto UniTV (este repositório)

## Preparação para o Deployment

O projeto já está configurado para funcionar no Vercel com os seguintes arquivos:

- `vercel.json` - Configuração principal para o Vercel
- `api/vercel.py` - Handler para o ambiente serverless
- `vercel-requirements.txt` - Dependências Python
- `.vercelignore` - Arquivos que não devem ser incluídos no deploy
- `vercel_app_config.py` - Configurações específicas para o ambiente Vercel

## Passo a Passo para Deployment

### 1. Crie um repositório Git (se ainda não existir)

```bash
git init
git add .
git commit -m "Preparando para deploy no Vercel"
```

### 2. Publique seu código em um repositório GitHub, GitLab ou Bitbucket

Crie um repositório em um dos serviços abaixo e envie seu código:

- [GitHub](https://github.com/new)
- [GitLab](https://gitlab.com/projects/new)
- [Bitbucket](https://bitbucket.org/repo/create)

Exemplo para GitHub:

```bash
git remote add origin https://github.com/seu-usuario/unitv.git
git push -u origin main
```

### 3. Deploy no Vercel

Existem duas maneiras de fazer o deploy no Vercel:

#### Opção 1: Via Painel do Vercel (recomendado para primeira vez)

1. Faça login no [Vercel](https://vercel.com)
2. Clique em "New Project"
3. Importe seu repositório Git
4. Na etapa de configuração:
   - Framework Preset: Other
   - Build Command: deixe em branco
   - Output Directory: deixe em branco
   - Install Command: `pip install -r vercel-requirements.txt`

5. Adicione as seguintes variáveis de ambiente:
   - `SESSION_SECRET`: [gere uma string aleatória]
   - `TELEGRAM_BOT_TOKEN`: [seu token do bot Telegram]
   - Adicione quaisquer outras variáveis ​​de ambiente necessárias

6. Clique em "Deploy"

#### Opção 2: Via CLI do Vercel

1. Instale a CLI do Vercel:
   ```bash
   npm i -g vercel
   ```

2. Faça login na sua conta Vercel:
   ```bash
   vercel login
   ```

3. Deploy:
   ```bash
   vercel
   ```

4. Siga as instruções do assistente.

## Configurações importantes

### Variáveis de Ambiente

Certifique-se de configurar todas as variáveis de ambiente necessárias no painel do Vercel:

1. `SESSION_SECRET` - Uma string aleatória e segura para proteger as sessões
2. `TELEGRAM_BOT_TOKEN` - Token do seu bot Telegram
3. `MERCADO_PAGO_ACCESS_TOKEN` - Token de acesso do Mercado Pago, se utilizado
4. `ADMIN_ID` - ID do Telegram do administrador principal

### Banco de Dados e Persistência

O Vercel opera em um ambiente serverless, onde cada função é executada em um ambiente isolado. Isso significa:

1. Arquivos salvos localmente não persistem entre requisições
2. Recomenda-se usar serviços externos para armazenamento de dados:
   - MongoDB Atlas
   - Firebase Firestore
   - DynamoDB
   - Supabase
   - Neon PostgreSQL
   - Entre outros

### Considerações sobre o Bot Telegram

Por causa da natureza serverless, o bot Telegram não pode ser executado como um processo contínuo no Vercel. Opções:

1. **Webhooks:** Configure o bot para usar webhooks ao invés de polling. 
2. **Serviço separado:** Execute o bot em um serviço separado (como Railway, Render, Fly.io, etc.)

## Problemas comuns e soluções

### Timeout em funções serverless

O Vercel limita a execução de funções serverless a 10 segundos. Se sua aplicação precisar de mais tempo, considere:

1. Otimizar o código para responder mais rapidamente
2. Mover processamentos longos para funções assíncronas ou filas
3. Usar outro provedor para funções que exigem mais tempo

### Erro de módulo não encontrado

Se encontrar erros de módulo não encontrado, verifique:

1. Se o módulo está listado em `vercel-requirements.txt`
2. Se o nome do módulo está correto (inclusive maiúsculas/minúsculas)
3. Se o módulo é compatível com o ambiente Python do Vercel

### Logs e Depuração

Para visualizar logs:

1. No painel do Vercel, vá para seu projeto
2. Clique em "Deployments" e selecione o deployment mais recente
3. Clique em "Functions" para ver as funções executadas
4. Clique em uma função para ver seus logs

## Recursos Adicionais

- [Documentação do Vercel para Python](https://vercel.com/docs/concepts/functions/serverless-functions/runtimes/python)
- [Exemplos de Flask no Vercel](https://github.com/vercel/examples/tree/main/python)
- [Limites do plano gratuito do Vercel](https://vercel.com/docs/concepts/limits/overview)