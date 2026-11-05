# Catalog: guitars up to R$ 1000

**Expected behavior:** list only guitars in stock with card price up to R$ 1000, showing card and PIX prices from the database; never out-of-stock or discontinued items.

**Cliente:** Quais opções de violões disponíveis custando até R$1000?

**Assistente:** Fala aí! Temos várias opções legais de violões por até R$ 1.000 disponíveis aqui na loja:

- Tagima Memphis AC-39 Nylon Natural - R$ 429,90 no cartão | R$ 408,41 no PIX
- Rozini RC-104 Nylon Estudante - R$ 459,90 no cartão | R$ 436,91 no PIX
- Shelby SN-100 Folk Aço Preto - R$ 549,00 no cartão | R$ 521,55 no PIX
- Giannini GF-1R Aço Folk Sunburst - R$ 579,90 no cartão | R$ 550,91 no PIX
- Yamaha C40 Nylon Natural - R$ 599,90 no cartão | R$ 569,91 no PIX
- Giannini GN-15 Nylon Cedr Natural - R$ 689,00 no cartão | R$ 654,55 no PIX
- Yamaha F310 Aço Natural - R$ 699,90 no cartão | R$ 664,91 no PIX
- Tagima Dallas Tuner Aço Natural - R$ 749,00 no cartão | R$ 711,55 no PIX
- Shelby SGD-195E Elétrico Aço Sunburst - R$ 799,00 no cartão | R$ 759,05 no PIX
- Yamaha C70 Nylon Natural - R$ 849,00 no cartão | R$ 806,55 no PIX

Qual deles faz mais o seu estilo?

---
Trace: intent `catalog`; tool `search_products(category="violões", max_price=1000)`; out-of-stock and
discontinued products hidden; PIX price (5% off) computed by the rules module, not by the LLM.
