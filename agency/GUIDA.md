# Guida rapida (italiano)

Tutto ciò che l'agenzia produce e mostra è in inglese. Questa pagina è solo per te.

## Cosa hai

Un'agenzia marketing che gira sul tuo Mac mini M5 Pro 64 GB, una AI alla volta in memoria,
senza token e senza pagare nulla. Il **cervello** è Qwen3.8-Flash-Next (125 miliardi di parametri,
quantizzato a 4 bit con la tabella sull'SSD); il 27B a 8 bit fa da seconda penna e da riserva
automatica. Gli **agenti** ricercano, scrivono, verificano ogni frase sulla guida, illustrano,
girano video fino a 4 minuti, doppiano, musicano, pubblicano, rispondono, cercano backlink da
siti autorevoli, leggono la posta e imparano dalle tue correzioni. L'**ufficio** ti mostra ogni
agente in diretta: cosa fa, a che passo è, quale modello ha in memoria.

## Le tre garanzie fisse (non si spengono)

1. **Non paga.** Ogni richiesta in uscita passa da un filtro che blocca pagamenti, pubblicità,
   checkout, abbonamenti e qualsiasi corpo con numeri di carta. X via API si paga a post, quindi
   X si pubblica solo dal browser con il tuo clic.
2. **Non crea account.** Lo scout prepara il kit (handle, bio, avatar, banner, primi post);
   l'iscrizione la fai tu.
3. **Niente azioni di massa.** Niente follow o amicizie automatiche; i commenti sotto i post
   altrui escono solo uno alla volta, dopo il tuo clic, con un tetto giornaliero.

## Installazione

```bash
cd AiToolsPrimer/agency
scripts/install_mac.sh            # strumenti, ambiente, LM Studio, llama.cpp, Chrome, pacchetti MLX, ComfyUI, ACE-Step, Agency.app
scripts/download_models.sh        # circa 130 GB
.venv/bin/agency doctor --benchmark   # prova i due cervelli sul tuo Mac e tiene il più forte che gira bene
.venv/bin/agency chrome-login x medium substack   # un login per piattaforma nel Chrome dell'agente
cp .env.example .env              # chiavi solo delle piattaforme che usi
.venv/bin/agency run              # http://127.0.0.1:8765, oppure l'app "Agency" nel Dock
```

Parte in prova a secco (`dry_run: true`): produce tutto, non pubblica nulla. Quando la coda ti
convince: `dry_run: false`, poi accendi `publishing`; `approval_required` resta acceso finché non
decidi tu.

## Come lavora, ogni giorno

Ricerca → piano (o il piano mensile) → scrittura a due penne con giudizio del cervello →
verifica frase per frase sui fatti della guida → limiti di piattaforma applicati dal codice →
immagini e video → sicurezza e regole → coda di approvazione → pubblicazione (API, browser con il
tuo clic, link a un tocco, o pacchetto da copiare). Ogni sera l'analista scrive le lezioni; ogni
domenica distilla le tue correzioni in regole di stile; il primo del mese arrivano report e piano
in PDF; dieci minuti prima del ciclo quotidiano c'è il briefing, anche a voce.

## Dove guardare

- **Office**: tutti gli agenti in diretta, interruttori, bottone KILL, "esegui ora".
- **Queue**: approva, modifica (le modifiche diventano correzioni), rifiuta.
- **Operator**: post compilati nel browser con screenshot; "Publish" è il tuo clic.
- **Outreach**: rete, domande delle community, posta, PR.
- **Deliverables**: piano, report, campagne, briefing.
- **Knowledge**: le schede di ogni piattaforma e gli aggiornamenti proposti dalla vigilanza settimanale.
- **Learning**: correzioni, regole di stile, set di addestramento per il modello unico.
- **Models**: benchmark dei cervelli, formazione, modello in memoria.

## Direttore a pagamento (opzionale, spento)

In `config/agency.yaml`: `director.provider: anthropic` e la chiave in `.env`, se un giorno vorrai
Claude come direttore. Tutto il resto resta locale.
