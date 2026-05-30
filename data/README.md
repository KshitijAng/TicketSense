# Seed data — synthetic provenance

**All 300 tickets in `batch_{1-6}.json` are synthetic. No real customer data,
no scraped data, no copied production records.**

## How the data was generated

1. **Initial draft — ChatGPT (GPT-5.4)**
   Tickets were generated in 6 thematic batches (50 each) using prompts that
   specified category mix, priority distribution, sentiment range, and edge
   cases per batch.

2. **Quality rewrite — Claude (Anthropic)**
   The initial draft suffered from a templating bug where 45 of 50 tickets
   in each batch shared identical body openings. Each ticket was hand-rewritten by 
   Claude to ensure unique bodies, varied tones, and realistic edge cases .

## Batches at a glance

| # | IDs | Theme | Representative |
|---|---|---|---|
| 1 | 001–050 | Routine / calm | Mixed everyday support |
| 2 | 051–100 | Angry / escalating | Churn threats, legal language, ALL-CAPS rage |
| 3 | 101–150 | Feature requests / positive | Fans, wishlists, emoji-heavy |
| 4 | 151–200 | Confused beginners | Short cryptic, broken English, typo-heavy |
| 5 | 201–250 | Critical production | P0 outages, security incidents, panic |
| 6 | 251–300 | Enterprise / B2B | Procurement, compliance, MSA redlines |

## Why this matters

This dataset exists purely to demonstrate the triage pipeline on realistic-
looking input. It is **not** representative of any real product, customer,
or vendor. Domain names (`acmecloud.io`, `atlas-pro.com`, etc.) are
invented. Sender names are randomized across cultures for diversity but
don't correspond to real individuals.
