# Financeiro Pessoal — Web App

Dashboard financeiro pessoal com login, banco de dados, wizard de preenchimento e PWA.

## Estrutura
```
app.py                  — Backend Flask completo
requirements.txt        — Dependências Python
Procfile                — Configuração produção
runtime.txt             — Versão Python
templates/
  landing.html          — Página inicial
  login.html            — Login
  cadastro.html         — Cadastro
  wizard.html           — Preenchimento passo a passo
  dashboard.html        — Dashboard principal
  base.html             — Template base (PWA + push)
static/
  app.css               — CSS mobile-first
  sw.js                 — Service Worker (PWA + notificações)
  icons/                — Ícones PWA (adicionar manualmente)
```

## Deploy no Railway

1. Suba todos os arquivos no GitHub (manter estrutura acima)
2. Conecte ao Railway via GitHub Repository
3. Adicione variável de ambiente: `SECRET_KEY` = qualquer string longa
4. Railway cria o banco PostgreSQL automaticamente se você adicionar o plugin
5. Gere o domínio em Settings → Networking → Generate Domain

## Variáveis de ambiente necessárias
- `SECRET_KEY` — chave secreta Flask (obrigatório)
- `DATABASE_URL` — gerado automaticamente pelo Railway PostgreSQL

## Rodar localmente
```bash
pip install -r requirements.txt
python app.py
# Acesse: http://localhost:5000
```

## Adicionar banco PostgreSQL no Railway
1. No projeto Railway, clique em "+ New"
2. Selecione "Database" → "PostgreSQL"
3. O Railway injeta DATABASE_URL automaticamente
