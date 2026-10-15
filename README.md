# Central de Pedidos Elétricos — backend

API e worker que recebem pedidos de materiais elétricos pelo WhatsApp (texto, áudio ou foto),
transformam o pedido em itens do catálogo com o Claude, confirmam com o cliente e devolvem um
link de carrinho Shopify, registrando cada pedido no Google Sheets.

Especificação completa: documento "Especificação do Backend — Central de Pedidos Elétricos via IA".

## Como funciona

1. A Meta chama `POST /webhooks/whatsapp`. A API valida a assinatura, enfileira a mensagem no
   Redis e responde em milissegundos.
2. O worker (`arq`) processa uma mensagem por vez por cliente:
   - fora do horário comercial, avisa o horário e para;
   - áudio é transcrito pelo Whisper; foto vai direto ao Claude como imagem;
   - o Claude devolve um JSON validado (itens, quantidades, atributos e intenções como
     "é só isso", "confirmar" ou "falar com atendente");
   - cada item é casado com o catálogo por similaridade (`pg_trgm`) e atributos (bitola,
     corrente, cor...). Se houver dúvida, o bot pergunta com até 3 opções numeradas;
   - no "é só isso", o bot mostra o resumo com preços e total e os botões Confirmar/Corrigir;
   - na confirmação, gera o link `https://loja/cart/variante:qtd,...` e agenda a exportação
     para a planilha.
3. A equipe usa o painel web (`painel/`, React) sobre a API `/api/v1`: caixa de entrada,
   assumir/devolver conversa, responder, pedidos, catálogo, horário comercial e usuários.

Preços e SKUs vêm sempre do banco; o modelo nunca informa preço.

## Estrutura

```
app/
  main.py              FastAPI (webhooks + API do painel)
  worker.py            jobs: process_incoming, export_order, sync_catalog + rotinas agendadas
  models.py            tabelas (SQLAlchemy 2)
  api/                 rotas: webhooks, auth/usuários, conversas, pedidos, catálogo, configurações
  services/
    conversation.py    motor da conversa (estados, dúvidas, resumo, confirmação, lembretes)
    extraction.py      prompt e chamada ao Claude com saída estruturada
    catalog.py         importação da planilha e casamento item → produto
    whatsapp.py        cliente da Cloud API e leitura do webhook
    transcription.py   Whisper
    cart.py            link de carrinho Shopify
    sheets.py          exportação de pedidos e leitura do catálogo no Google Sheets
    business_hours.py  horário comercial e feriados
    privacy.py         retenção de 1 ano (LGPD)
migrations/            Alembic
data/catalogo_exemplo.csv  20 produtos de exemplo (formato da aba "Catalogo")
tests/                 pytest com banco real e dublês de WhatsApp, Claude e Whisper
painel/                painel web (React + Vite + TanStack Query)
  src/pages/           Conversas, Pedidos, Catálogo, Horário, Usuários, Login
  src/api.ts           cliente HTTP (token em memória, renovação pelo cookie)
```

## Rodando localmente

Requisitos: Python 3.12+, [uv](https://docs.astral.sh/uv/), PostgreSQL 16 e Redis 7.

```bash
uv sync
cp .env.example .env            # preencha; para desenvolvimento use APP_ENV=development
uv run alembic upgrade head
uv run python -m app.cli create-admin --nome "Seu Nome" --email voce@loja.com
uv run python -m app.cli import-catalog data/catalogo_exemplo.csv
uv run python -m app.cli seed-hours

uv run uvicorn app.main:app --reload        # API em http://localhost:8000/docs
uv run arq app.worker.WorkerSettings        # worker, em outro terminal
```

Painel (em outro terminal), em http://localhost:3000 — o Vite encaminha `/api` para a porta 8000:

```bash
cd painel
npm install
npm run dev
```

Para experimentar o painel sem WhatsApp, popule dados fictícios (usuários `admin@demo.com`,
`sueli@demo.com` e `ana@demo.com`, senha `demo12345`):

```bash
uv run python -m app.cli seed-demo
```

Sem `WHATSAPP_ACCESS_TOKEN`, a API e o worker ficam em modo simulação: as mensagens que seriam
enviadas ao WhatsApp só aparecem no log.

Para receber mensagens reais em desenvolvimento, exponha a porta 8000 (ex.: `cloudflared` ou
`ngrok`) e cadastre `https://<url>/webhooks/whatsapp` no app da Meta com o
`WHATSAPP_VERIFY_TOKEN`.

## Testes

```bash
createdb pedidos_test
uv run pytest
uv run ruff check . && uv run ruff format --check .
```

Os testes usam o banco `pedidos_test` (ou `DATABASE_URL`), sem chamar nenhuma API externa.

```bash
cd painel && npm run typecheck && npm test
```

## Catálogo (aba "Catalogo" da planilha)

| coluna | exemplo |
| --- | --- |
| sku | CAB-FLX-25-AZ |
| nome_tecnico | Cabo Flexível 2,5mm² 750V Azul |
| categoria | cabos |
| unidade_venda | metros, unidades, rolos, caixas... |
| preco | 2,10 |
| shopify_variant_id | 44112233445566 |
| atributos | bitola_mm2=2.5; cor=Azul; tensao_v=750 |
| sinonimos | fio 2.5; fio de dois e meio; fio de duas metade |
| ativo | sim / não |

Chaves de atributo aceitas: `bitola_mm2`, `corrente_a`, `tensao_v`, `cor`, `polos`,
`potencia_w`, `diametro_mm`, `tipo`. O worker sincroniza a cada 15 minutos; o botão
"Sincronizar" do painel chama `POST /api/v1/products/sync`.

## Deploy (VPS)

```bash
cp .env.example .env && nano .env
mkdir -p secrets && cp ~/google-service-account.json secrets/
docker compose up -d --build
docker compose exec api python -m app.cli create-admin --nome "Admin" --email admin@loja.com
```

O serviço `caddy` é construído a partir de `painel/Dockerfile`: compila o painel e o serve em
`https://DOMAIN/`, encaminhando `/api`, `/webhooks` e `/health` para a API (mesma origem, sem
CORS). O Caddy emite o certificado HTTPS para `DOMAIN` automaticamente. Webhooks a cadastrar:

- Meta: `https://DOMAIN/webhooks/whatsapp` (campo `messages`)
- Shopify: `https://DOMAIN/webhooks/shopify/orders` (evento `orders/create`)

## Ainda não implementado

- Mensagens de template (lembrete fora da janela de 24 h e retorno do atendente).
- Eventos em tempo real para o painel: hoje ele consulta a API a cada 4–10 s (o worker já
  publica em `painel:eventos` no Redis; falta o endpoint WebSocket).
- Edição de itens do pedido pelo atendente no painel.
- Métricas (`/api/v1/metrics`) e dicionário de gírias pelo painel (a tabela já existe).
- Armazenamento de mídia no Cloudflare R2 (hoje vai para o volume `media`) e backup automático.
- Busca semântica por embeddings; o casamento atual usa `pg_trgm` + atributos e deve ser
  calibrado com o catálogo real (`MATCH_CONFIDENCE_THRESHOLD`).
- Integração com ERP.
