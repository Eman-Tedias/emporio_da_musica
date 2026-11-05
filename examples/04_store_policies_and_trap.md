# Store information and a prior-knowledge trap

**Expected behavior:** address and Saturday hours from the manual; for the physical store purchase, state that the regret right is for online purchases only and offer the preference exchange (manual 4.3: up to 7 days, product in perfect condition, subject to availability).

**Cliente:** Qual o endereço da loja?

**Assistente:** Fala aí! O endereço da Empório da Música é Rua 14 de Maio, 3200 - Centro, Campo Grande - MS, 79202-333. Qualquer coisa é só chamar!

**Cliente:** e abre sábado?

**Assistente:** Fala aí! Sim, a loja abre aos sábados das 09:00 às 13:00. Qualquer dúvida é só chamar!

---

**Cliente:** Comprei na loja física e me arrependi, posso devolver em 7 dias?

**Assistente:** E aí! O direito de arrependimento em até 7 dias corridos, conforme previsto em nossas políticas, é válido apenas para compras feitas online. Para compras em loja física, o que vale é a troca por preferência: você pode trocar por outro modelo, cor ou tamanho em até 7 dias, com o produto em perfeito estado e na embalagem original, mediante disponibilidade.

---
Trace: policy questions go to the manual search without an LLM in the retrieval step. The last question is a
trap from the generation golden set: general knowledge says "7 days to return", but the manual (4.1) limits the
regret right to online purchases.
