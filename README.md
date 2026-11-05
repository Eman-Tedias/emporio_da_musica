# Empório da Música - customer service agent

A Python customer service agent for Empório da Música, a musical instrument store in Campo Grande (MS). It answers
catalog, price, order and store policy questions with the store's persona, using the CSV data (Postgres) and the
policies manual (RAG over pgvector), and refuses what is out of scope.

The design principle: **no security or business decision depends on an LLM output**. The database provides the data,
pure functions apply the manual's rules, code decides what each request may trigger, and the LLMs only classify,
pick tools and write the answer, always inside deterministic guardrails.

## Contents
1. [How to run](#how-to-run)
2. [Architecture](#architecture)
3. [Technical decisions](#technical-decisions)
4. [Evaluation and tests](#evaluation-and-tests)
5. [Assumptions about the data and the manual](#assumptions-about-the-data-and-the-manual)
6. [Known limitations and next steps](#known-limitations-and-next-steps)
7. [Conversation examples](#conversation-examples)
8. [AI coding assistant usage](#ai-coding-assistant-usage)

## How to run

### Requirements
- Docker Desktop (or Docker Engine with Compose).
- API keys: **Google Gemini** and **OpenAI** (both are used: see [models](#models-and-providers)).
- Optional: Langfuse keys for tracing. Without them, tracing is disabled automatically.
- The challenge files. **The `data/` folder is not versioned on purpose** (it contains customer data): copy
  `desafio_tecnico_ai_eng - *.csv` and `políticas_da_loja.pdf` into `data/`.

### With Docker (recommended)
```bash
cp .env.example .env          # fill in the keys and choose the database passwords
docker compose up -d --build
```
Open **http://localhost:8501** (chat interface). The API is at **http://localhost:8000/docs**.

Compose starts, in order: `db` (Postgres 16 + pgvector) → `ingest` (loads the CSVs and the manual, then exits) →
`api` (FastAPI, after ingestion succeeds) → `ui` (Streamlit, after the API is healthy).

### Local development
```bash
python -m venv .venv && .venv\Scripts\activate      # Python 3.12
pip install -r requirements.txt
docker compose up -d db
python -m app.ingest                 # CSVs -> Postgres
python -m app.rag.ingest             # policies manual -> pgvector
uvicorn app.api.main:app --port 8000
streamlit run app/ui/streamlit_app.py
```

### Tests and evaluation
```bash
pytest                               # 254 tests (integration tests are skipped if the database is down)
pytest -m "not integration"          # 199 tests, no database or API key needed
python -m app.evals.eval_retrieval   # retrieval strategies compared on the golden set
```

## Architecture

```
Streamlit (chat + trace of the last turn)  ->  FastAPI (server-side session, rate limit)
        |
[1] Deterministic input guardrail (code)
    Unicode normalization, size limit, injection patterns, tag removal,
    CPF/card masked, email/phone replaced by tokens kept in the session
        |
[2] In parallel, on different providers:
    [2a] LLM guardrail (gpt-5.6-luna): {suspicious, reason}
    [2b] Parser/router (gemini-3.5-flash-lite): intents, entities, rewritten_question
        |  continues only if 2a approves; rewritten_question goes through the regex again
[3] Dispatch (code): fixed table intent -> capabilities
        |
   +----+-----------------------+-----------------------+   (in parallel)
[4a] Data sub-agent          [4b] Policy search        [4c] Order lookup
     LLM + catalog tools          code, no LLM              code, no LLM
     + rule calculators           small-to-big on pgvector  credential from the session
   +----+-----------------------+-----------------------+
        |
[5] Composition (gemini-3.5-flash-lite): persona, structured output, cites manual sections
        |
[6] Deterministic output guardrail: every R$ value and percentage must come from the evidence,
    no third-party personal data, cited sections must have been retrieved
        |
Logs (one line per turn) + logs/traces.jsonl + Langfuse (tokens, cost, timings)
```

Repository layout: `app/ingest` (CSV loading), `app/db` (schema), `app/calculators` (manual rules),
`app/tools` (catalog, orders, safe arithmetic), `app/rag` (chunking and retrieval), `app/guardrails`,
`app/llm` (providers, fallback, prices), `app/agents` (prompts, data agent, orchestrator), `app/api`, `app/ui`,
`app/evals` (golden sets and retrieval evaluation), `app/tests`.

## Technical decisions

### Agent approach: native tool calling, no framework
- Native function calling (the same Reason/Act loop as ReAct, without parsing `Thought/Action` text) over the
  provider SDKs. LangChain/LangGraph were not used: the flow is linear and fits in a few hundred readable lines;
  LangGraph would pay off with human-in-the-loop, complex branching or durable execution.
- **Router + capabilities instead of one agent with every tool.** The router only classifies (closed enum); a
  fixed table in code decides what each intent may trigger. Only the data sub-agent has tools; policy search and
  order lookup are fully determined calls, so they run as code without an LLM (fewer calls, less latency, fewer
  LLMs exposed to user text).
- **No text-to-SQL**: the questions are predictable, so typed tools with parameterized queries are safer and more
  accurate. Text-to-SQL is listed as a next step for open analytical questions.
- **The LLM never does arithmetic.** The manual's numeric rules (5% PIX discount not stacking on promotions,
  minimum installment tiers, shipping, return windows) are pure, tested functions. Catalog tools already return
  card price, PIX price and maximum installments. For values that combine tool results (a cart total) there is
  a `calculate` tool evaluated with `ast` over a whitelist (numbers, `+ - * /`, parentheses), never `eval`.

### Models and providers
| Role | Primary | Fallback |
|---|---|---|
| LLM guardrail | gpt-5.6-luna | gemini-3.5-flash-lite |
| Parser/router | gemini-3.5-flash-lite | gpt-5.6-luna |
| Data sub-agent (multi-step tool calling) | gpt-5.6-luna | gemini-3.5-flash-lite |
| Composition | gemini-3.5-flash-lite | gpt-5.6-luna |
| Embeddings | text-embedding-3-small | |

- Light, cheap models: the hard parts are done by code, so the models classify, choose tools and write.
- **Guardrail and router are separate calls on different providers**: if one call did both, an attack that fools
  one fools the other, and the free-text `rewritten_question` could carry injected instructions downstream.
- **Provider fallback on every call** (timeout, 429, 5xx or output that fails the schema), implemented once in
  `LLMClient`. Also mitigates the Gemini free tier limits.
- OpenAI is used through the **Responses API**: `gpt-5.6-luna` is a reasoning model and does not accept tools in
  Chat Completions.

### Retrieval architecture
- **PDF extraction**: pypdf, pymupdf4llm and Docling were compared on the real manual. pypdf breaks the text word
  by word and destroys the tables; Docling and pymupdf4llm give equivalent quality here, but Docling took 81 s
  (plus torch and model downloads) against 2.4 s. **pymupdf4llm** was chosen (OCR off: the PDF is digital).
- **Chunking by section**: the Markdown headings give one chunk per section/subsection (26), with the hierarchy
  as metadata; running headers/footers are removed generically (lines repeated on most pages).
- **Small-to-big semantic search** (pgvector): list items and table rows (92 pieces, each prefixed with its
  section title) are embedded and searched; the whole parent section is what reaches the LLM.
- Chosen by measurement over a 30-case golden set (see [evaluation](#evaluation-and-tests)): it beat section-level
  semantic search and hybrid search (vector + Portuguese full-text with Reciprocal Rank Fusion).

### Prompt strategy
- One short prompt per role (guardrail, parser, data agent, composer) in `app/agents/prompts.py`, written in
  English, with answers in Brazilian Portuguese.
- **Structured output with Pydantic** in every call except the tool loop: the guardrail returns
  `{suspicious, reason}`, the parser a closed enum of intents, the composer `{answer, cited_sections}`.
- **Persona from the manual** (section 7.1): informal but professional, "like a friend who knows music".
- The composer may use only the context, must copy prices exactly, cite the manual sections it used, show
  promotions with original price and percentage (manual 6.2), and offer a human attendant when it does not know.
- **Random delimiters (spotlighting)**: every untrusted text (customer message, history, rewritten question,
  data from the database and the manual) goes inside tags with a random suffix generated per turn
  (`<message-a3f9c1e2>`), and the system prompt says their content is data, never instructions.
- Conversation memory: the parser rewrites follow-ups into standalone questions ("e no pix?" → "quanto custa o
  Takamine GD20 no PIX?"), so the other steps do not need the whole history.

### Security (OWASP Top 10 for LLM Applications 2025)
- **Prompt injection**: Unicode normalization (invisible characters removed before matching), regex patterns
  from `policies.yaml`, HTML/XML tag removal, LLM guardrail on another provider, closed schemas, random
  delimiters, only approved messages enter the history.
- **Sensitive data**: email and phone become tokens (`[EMAIL_1]`) and the real value stays in the server-side
  session; the code injects it into the order lookup, so **the LLM never sees a credential**. CPF and card numbers
  (validated by check digits/Luhn) are masked and discarded. Logs, traces and Langfuse only get masked text.
- **Authorization inside the database**: the agent connects as `agent_reader` (read-only) and cannot read
  `customers`, `orders` or `order_items`. The only way to an order is `get_authorized_order(order_id, email,
  phone)`, a `SECURITY DEFINER` function that returns the order only when the credential belongs to its owner,
  without customer data. Order ids must appear in the customer's own messages, failed lookups are limited to 3.
- **Misinformation**: the output guardrail replaces any answer with an R$ value or percentage that is not in the
  evidence of the turn (tool results, retrieved manual text or the customer's own message).
- **Unbounded consumption**: 1,000 characters per message, 20 messages per minute per session, 15 s timeout per
  LLM call, max output tokens per role, max 5 tool steps, idle sessions expire after 1 hour.
- Dependencies pinned; the container runs as a non-root user; `.env` and data are not in the image.

### Interface
FastAPI is the product (`POST /chat`, `GET /health`); Streamlit is a simple demo client with a toggle that shows
the trace of the last turn. The challenge focuses on the agent, so the UI was kept minimal.

### Conversation history
Kept in a server-side in-memory session (masked text, a window of the last 6 exchanges, credential tokens,
verified orders). It makes sense for the experience (follow-ups like "e no pix?" and "é o pedido 1") and the client
never chooses its own session id. Persisting it in Postgres (the `history_writer` role already exists) is a next
step.

### Data treatment
- CSVs validated row by row with Pydantic (types, money as `Decimal`, empty strings → `NULL`, JSON specs, phone
  digits) and loaded in one transaction; invalid rows stop the ingestion with file and line.
- Schema with `NUMERIC(10,2)` for money, `CHECK` constraints (status, prices, percentages, phone, email, payment
  method, tracking code) and foreign keys.
- Data quality findings and how each is handled: see [assumptions](#assumptions-about-the-data-and-the-manual).

### Observability
- One INFO log line per turn with intents, total time, cost, number of LLM calls and the time of each stage;
  warnings for provider fallback, blocked messages and answers replaced by the output guardrail.
- **Langfuse** (chosen over LangSmith because it is open source, can be self-hosted and its cloud service is
  cheaper; it also does not require LangChain). Each turn is a trace grouped by session, with typed observations
  (guardrail, generation with tokens and cost, agent, tool, retriever, embedding). Costs are computed locally
  from `app/llm/pricing.py` (recent models may be missing from Langfuse's price table).
- First measurement: a catalog turn with a cart took 12.6 s and US$ 0.002 (the data sub-agent was 8.6 s of it);
  a policy turn took 3.6 s and US$ 0.001.

## Evaluation and tests

**Retrieval** (`app/evals/retrieval_golden_set.json`, 30 cases: facts, exact terms, colloquial, two-section and
negative questions; 6 kept as holdout). Results on the 20 answerable non-holdout cases:

| Strategy | recall@1 | recall@3 | MRR | nDCG@3 | evidence@3 |
|---|---|---|---|---|---|
| section, semantic | 0.70 | 1.00 | 0.858 | 0.887 | 1.00 |
| section, hybrid (RRF) | 0.80 | 0.975 | 0.908 | 0.912 | 1.00 |
| **small-to-big, semantic (production)** | **0.85** | **1.00** | **0.942** | **0.957** | 1.00 |
| small-to-big, hybrid (RRF) | 0.85 | 0.975 | 0.950 | 0.944 | 1.00 |

- The gain came from exact terms (PIX, SEDEX, boleto: recall@1 from 0.50 to 1.00): in a whole section the term is
  diluted, in a small piece it dominates the embedding.
- recall@3 = 1.00: the right section always reaches the LLM (top-1 misses are neighboring sections).
- Similarity alone cannot separate unanswerable questions (negatives up to 0.54, answerable down to 0.48), so
  abstention is left to the composer with the context.
- Caveats: small corpus (top-3 covers 12% of it, so numbers are optimistic) and 20 questions.

**Tests** (254, TDD in the deterministic parts): ingestion (38), database schema, permissions and the authorized
order function (29), rule calculators (28), tools (36), RAG (28), guardrails (46), agents with a fake LLM:
dispatch, order shortcut, grounding, guardrails around the LLM, fallback, costs (40), API (9).

**Generation golden set** (`app/evals/generation_golden_set.json`, 14 cases including prior-knowledge traps such
as "I bought in the physical store, can I return it in 7 days?") is ready; the LLM-as-judge run is a next step.

## Assumptions about the data and the manual
- **Duplicated email**: customers 11 and 43 share `bruno.martins@jmail.com` (same city, similar names). Assumed to
  be the same person registered twice; both records kept, ingestion prints a warning.
- **Order totals** 3 and 20 differ from the sum of current item prices: the order total is the truth of the order
  (price at the time or discount); orders are never recalculated.
- **Orders 9, 16 and 18** were split below the manual's minimum installment: reported as they are; the rule
  applies to new simulations only.
- **Product 130** is `coming_soon` but appears in orders: the catalog shows it as "coming soon"; orders as they are.
- **Categories 6, 7 and 8** have no products: the agent says so instead of inventing.
- **The manual** lists two WhatsApp numbers ((67) 3341-4444 and (67) 3321-4500) and two spellings of the email;
  both are treated as official contacts.
- Rule interpretations: "up to 3x without minimum (except below R$ 50)" means 2x/3x installments cannot be below
  R$ 50; the metropolitan region is Campo Grande; regret and preference returns count from delivery
  (`estimated_delivery`, the data has no actual delivery date); defect returns count 30 days from purchase.
- Model prices used for cost tracking come from aggregators citing the providers' pages (not verified on the
  official pages); Gemini free tier calls are not actually billed.

## Known limitations and next steps
- Sessions live in memory: a restart loses them and several API instances do not share them (next: Postgres with
  the existing `history_writer` role, or Redis).
- Email + order number is weak authentication; in production the channel (WhatsApp number) would identify the
  customer.
- Run the generation evaluation (faithfulness, abstention, correctness with an LLM judge) and a parser
  evaluation (intent accuracy, recall on paraphrased injections); run the retrieval holdout.
- The data sub-agent on gpt-5.6-luna is the latency bottleneck; compare it with Flash-Lite.
- A dedicated injection classifier (Google Model Armor, `gpt-oss-safeguard` or a DeBERTa model) between the regex
  and the LLM guardrail.
- Reranker if the generation eval shows confusion between neighboring sections; BM25 and an HNSW index if the
  manual grows; Docling/OCR for scanned documents.
- Text-to-SQL (read-only) for open analytical questions; one database role per capability.
- Incremental ingestion (today it recreates the tables and the manual embeddings on every `docker compose up`).
- Accepting values typed by the customer as evidence avoids replacing answers that repeat the customer's budget,
  at the cost of a small risk of the model echoing a wrong value the customer stated.

## Conversation examples
Real conversations with the running system are in [`examples/`](examples/).

## AI coding assistant usage
I used Claude Code as a sparring partner: I defined the architecture and made the decisions, and used it to reason through alternatives and trade-offs before each choice (for example, the guardrail and router split, the extraction library and the retrieval strategy, which were then settled by measurement). I followed a test-driven development (TDD) approach instead of spec-driven development (SDD): tests and golden sets came before each module, and the code was written to make them pass. Claude Code also assisted with the code in a guided way in some of the features.
