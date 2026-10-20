# Guida rapida (italiano)

Tutto il contenuto prodotto è in inglese. Questa è solo la guida per te.

## Cosa hai

Un'agenzia marketing che gira sul tuo Mac mini M5 Pro 64 GB, senza token e senza
pagare nulla. Un **direttore** (Qwen3.8-27B) pianifica e controlla; gli **agenti**
ricercano, scrivono, illustrano, girano video fino a 4 minuti, doppiano, musicano,
pubblicano e imparano. Un **pannello** locale ti dà interruttori, coda di approvazione
e log.

## Cosa NON fa mai (garanzie fisse, non disattivabili)

1. **Non paga.** Ogni richiesta in uscita passa da un filtro che blocca processori di
   pagamento, pubblicità, checkout, abbonamenti e qualsiasi corpo con numeri di carta.
2. **Non crea account.** Lo scout trova piattaforme nuove e prepara tutto (handle, bio,
   avatar, banner, primi post); l'iscrizione la fai tu con un clic.
3. **Non fa azioni di massa.** Niente richieste di amicizia, follow o commenti automatici
   sui contenuti altrui: violano i termini e fanno bannare i profili. Risponde solo ai
   commenti sotto i tuoi post, e anche quello lo attivi tu.

## Installazione

```bash
scripts/install_mac.sh        # strumenti, ambiente Python, LM Studio, ComfyUI, ACE-Step
scripts/download_models.sh    # circa 90 GB di modelli
.venv/bin/agency doctor       # verifica tutto
cp .env.example .env          # inserisci le chiavi delle piattaforme che usi
.venv/bin/agency run          # pannello su http://127.0.0.1:8765
```

Parte in **prova a secco** (`dry_run: true` in `config/agency.yaml`): produce tutto ma non
pubblica. Quando la coda ti convince, metti `dry_run: false`.

## Interruttori principali

- `master_enabled`: interruttore generale (il bottone rosso KILL lo spegne).
- `publishing`: finché è spento nulla esce dal Mac, tutto resta in coda.
- `approval_required`: ogni pezzo aspetta il tuo clic.
- `make_videos`, `make_shorts`, `make_images`, `write_articles`, `write_posts`.
- `auto_reply_own_posts`: risponde ai commenti sotto i tuoi post.
- `discover_platforms` e `prepare_signup_kits`: lo scout cerca piattaforme nuove e prepara
  il kit di iscrizione.
- Un interruttore per ogni piattaforma nella pagina Platforms.

## Ritmo giornaliero

07:30 UTC ciclo del giorno, ogni 30 minuti commenti, 22:00 analisi, lunedì scout. Dal
pannello puoi lanciare tutto a mano, compreso "fai un video su X di 240 secondi".

## Direttore a pagamento (opzionale, spento)

In `config/agency.yaml` metti `director.provider: anthropic` e la chiave in `.env` se un
giorno vorrai Claude come direttore. Tutto il resto resta locale.
