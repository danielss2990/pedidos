# Central de Pedidos Elétricos — backend

API e worker que recebem pedidos de materiais elétricos pelo WhatsApp (texto, áudio ou foto),
transformam o pedido em itens do catálogo com um modelo de IA aberto, confirmam com o cliente e
fecham o pedido pelo próprio WhatsApp (retirada ou entrega e forma de pagamento). Não há
e-commerce: a equipe separa, cobra e entrega acompanhando pelo painel, que exporta os pedidos em
CSV/XLSX.

Todo o software é open source e roda no servidor do cliente: FastAPI, PostgreSQL, Valkey, Ollama
(modelos Qwen2.5), faster-whisper, React e Caddy. A única exceção é a API Oficial do WhatsApp
(Meta), que é o canal do cliente e o único permitido pelo WhatsApp.

Especificação completa: documento "Especificação do Backend — Central de Pedidos Elétricos via IA".

## Como funciona

1. A Meta chama `POST /webhooks/whatsapp`. A API valida a assinatura, enfileira a mensagem no
   Valkey e responde em milissegundos.
2. O worker (`arq`) processa uma mensagem por vez por cliente:
   - fora do horário comercial, avisa o horário e para;
   - áudio é transcrito pelo Whisper rodando localmente (faster-whisper); foto vai para o modelo
     de visão (o bot avisa o cliente que está lendo, porque em CPU pode levar minutos);
   - o modelo aberto, servido pelo Ollama, devolve um JSON validado contra o schema (itens,
     quantidades, atributos e intenções como "é só isso", "confirmar" ou "falar com atendente");
     se o JSON vier fora do formato, ele tenta mais uma vez mostrando o erro ao modelo;
   - cada item é casado com o catálogo por similaridade (`pg_trgm`) e atributos (bitola,
     corrente, cor...). Se houver dúvida, o bot pergunta com até 3 opções numeradas;
   - no "é só isso", o bot mostra o resumo com preços e total e os botões Confirmar/Corrigir;
   - ao confirmar, o bot fecha o pedido sem chamar a IA: pergunta retirada ou entrega
     (endereço digitado ou localização do WhatsApp), forma de pagamento (Pix, cartão ou
     dinheiro) e, se for dinheiro na entrega, o troco. Na retirada com Pix já envia a chave;
   - o pedido fica "Novo" no painel. Enquanto ele está com a equipe, o bot
     só avisa o cliente que a mensagem foi recebida (no máximo uma vez a cada 12 h).
3. A equipe usa o painel web (`painel/`, React) sobre a API `/api/v1`:
   - **Pedidos › Em andamento**: informar o frete (o cliente recebe o total e a chave Pix),
     marcar como pago e avançar: em separação → pronto para retirada / saiu para entrega →
     concluído. Cada etapa avisa o cliente no WhatsApp (dentro da janela de 24 h da Meta);
   - **Conversas**: fila de atendimento, assumir/devolver ao bot, responder, ver áudios e fotos
     (ex.: comprovantes de Pix);
   - **Exportar** pedidos de um período em XLSX (LibreOffice Calc ou Excel) ou CSV;
   - catálogo (edição e importação/exportação CSV/XLSX), horário comercial e usuários.

Preços e SKUs vêm sempre do banco; o modelo nunca informa preço.

## Estrutura

```
app/
  main.py              FastAPI (webhooks + API do painel)
  worker.py            job process_incoming + rotinas agendadas (lembretes, LGPD)
  models.py            tabelas (SQLAlchemy 2)
  api/                 rotas: webhooks, auth/usuários, conversas, pedidos, catálogo, configurações
  services/
    conversation.py    motor da conversa (estados, dúvidas, resumo, confirmação, lembretes)
    extraction.py      prompt e chamada ao Ollama com saída estruturada (schema JSON)
    catalog.py         importação do catálogo e casamento item → produto
    whatsapp.py        cliente da Cloud API e leitura do webhook
    transcription.py   Whisper local (faster-whisper)
    fulfillment.py     fechamento (entrega/pagamento) e ações da equipe sobre o pedido
    export.py          CSV/XLSX: exportação de pedidos e catálogo, leitura para importação
    business_hours.py  horário comercial e feriados
    privacy.py         retenção de 1 ano (LGPD)
migrations/            Alembic
data/catalogo_exemplo.csv  20 produtos de exemplo (formato aceito pela importação)
tests/                 pytest com banco real e dublês de WhatsApp, Ollama e Whisper
painel/                painel web (React + Vite + TanStack Query)
  src/pages/           Conversas, Pedidos, Catálogo, Horário, Usuários, Login
  src/api.ts           cliente HTTP (token em memória, renovação pelo cookie)
```

## Rodando localmente

Requisitos: Python 3.12+, [uv](https://docs.astral.sh/uv/), PostgreSQL 16, Valkey 8 (ou Redis)
e [Ollama](https://ollama.com) com os modelos baixados:

```bash
ollama pull qwen2.5:7b      # texto
ollama pull qwen2.5vl:7b    # fotos de listas
```

O Whisper baixa o modelo (`WHISPER_MODEL`, padrão `small`) na primeira transcrição.

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

Para receber mensagens reais em desenvolvimento, exponha a porta 8000 com um túnel HTTPS e
cadastre `https://<url>/webhooks/whatsapp` no app da Meta com o
`WHATSAPP_VERIFY_TOKEN`.

## Testes

```bash
createdb pedidos_test
uv run pytest
uv run ruff check . && uv run ruff format --check .
```

Os testes usam o banco `pedidos_test` (ou `DATABASE_URL`) e simulam WhatsApp, Ollama e Whisper;
não precisam dos modelos baixados.

```bash
cd painel && npm run typecheck && npm test
```

## Catálogo (importação CSV/XLSX)

No painel, **Catálogo › Importar CSV/XLSX** cria ou atualiza produtos pelo SKU; **Exportar planilha**
baixa o catálogo atual no mesmo formato, que serve de modelo. Pela linha de comando:
`python -m app.cli import-catalog arquivo.xlsx`. CSV pode usar `;` ou `,`.

| coluna | exemplo |
| --- | --- |
| sku | CAB-FLX-25-AZ |
| nome_tecnico | Cabo Flexível 2,5mm² 750V Azul |
| categoria | cabos |
| unidade_venda | metros, unidades, rolos, caixas... |
| preco | 2,10 |
| atributos | bitola_mm2=2.5; cor=Azul; tensao_v=750 |
| sinonimos | fio 2.5; fio de dois e meio; fio de duas metade |
| ativo | sim / não |

Chaves de atributo aceitas: `bitola_mm2`, `corrente_a`, `tensao_v`, `cor`, `polos`,
`potencia_w`, `diametro_mm`, `tipo`. Linhas sem SKU, nome ou preço são ignoradas.

## Deploy (servidor)

**Hardware:** os modelos rodam em CPU, então o servidor precisa de memória para carregar os dois
modelos de 7B (cerca de 5–6 GB cada, quantizados) mais o Whisper e o banco. Recomendado: 8 vCPUs
dedicadas e 32 GB de RAM (16 GB é o mínimo, com só um modelo carregado por vez). Estimativa a
validar no hardware real: texto em 10–30 s, foto em 1–3 min. O worker processa um cliente por
vez, por isso o tempo de espera cresce nos horários de pico.

```bash
cp .env.example .env && nano .env
docker compose up -d --build        # na primeira vez, ollama-pull baixa os modelos (~10 GB)
docker compose logs -f ollama-pull  # acompanhe até terminar
docker compose exec api python -m app.cli create-admin --nome "Admin" --email admin@loja.com
docker compose exec api python -m app.cli import-catalog /caminho/catalogo.xlsx
```

O serviço `caddy` é construído a partir de `painel/Dockerfile`: compila o painel e o serve em
`https://DOMAIN/`, encaminhando `/api`, `/webhooks` e `/health` para a API (mesma origem, sem
CORS). O Caddy emite o certificado HTTPS para `DOMAIN` automaticamente. Webhooks a cadastrar:

- Meta: `https://DOMAIN/webhooks/whatsapp` (campo `messages`)

Configure no `.env` o endereço da loja e a chave Pix (`LOJA_ENDERECO`, `PIX_CHAVE`,
`PIX_TITULAR`); eles aparecem nas mensagens de fechamento.

## Ainda não implementado

- Mensagens de template (lembrete fora da janela de 24 h e retorno do atendente).
- Eventos em tempo real para o painel: hoje ele consulta a API a cada 4–10 s (o worker já
  publica em `painel:eventos` no Valkey; falta o endpoint WebSocket).
- Edição de itens do pedido pelo atendente no painel.
- Métricas (`/api/v1/metrics`) e dicionário de gírias pelo painel (a tabela já existe).
- Backup automático do banco e das mídias (ex.: `pg_dump` + restic para um armazenamento S3
  compatível como MinIO ou Garage).
- Busca semântica por embeddings; o casamento atual usa `pg_trgm` + atributos e deve ser
  calibrado com o catálogo real (`MATCH_CONFIDENCE_THRESHOLD`).
- Confirmação automática de Pix (hoje a equipe confere o comprovante e marca como pago).
- Avaliação da IA com pedidos reais do cliente (acerto da extração de texto, áudio e fotos com o
  modelo aberto) e ajuste do prompt.
- Integração com ERP.
