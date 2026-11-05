# Price, follow-up and a two-item cart

**Expected behavior:** price with card and PIX from the database; the follow-up "e no pix?" understood from the history; the cart total and the installment value computed by tools (R$ 799,80 in 6x of R$ 133,30), never by the LLM.

**Cliente:** Quanto custa o Takamine GD20?

**Assistente:** Fala aí! O Takamine GD20 Dreadnought Natural sai por R$ 2.199,00 no cartão ou R$ 2.089,05 no Pix, e você ainda pode parcelar em até 12x. Aproveita que ele está disponível em estoque!

**Cliente:** e no pix?

**Assistente:** No Pix, o violão Takamine GD20 sai por R$ 2.089,05, beleza?

---

**Cliente:** Quanto fica o Yamaha C40 mais o ukulele Kala KA-15S em 6x?

**Assistente:** O violão Yamaha C40 custa R$ 599,90 e o ukulele Kala KA-15S, R$ 199,90. Total no cartão: R$ 799,80, em 6 vezes de R$ 133,30.

---
Trace: the parser rewrote "e no pix?" as "quanto custa o Takamine GD20 no PIX?". The cart used
`get_product` twice, `calculate("599.90 + 199.90")` and `simulate_installments(799.80, 6)`: the LLM chose the
operations, the code did the arithmetic and checked the R$ 80 minimum installment for 4x to 6x.
