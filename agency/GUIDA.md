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
scripts/install_mac.sh            # strumenti, ambiente, LM Studio, llama.cpp, Chrome, pacchetti MLX, mlx-speech, ltx-2-mlx, ComfyUI, ACE-Step, Agency.app
cp .env.example .env              # SSD esterno? scrivi qui AGENCY_MODELS=/Volumes/<disco>/models prima di scaricare (vedi sotto)
scripts/download_models.sh        # circa 260 GB, tutti in una cartella
.venv/bin/agency doctor --benchmark   # prova i due cervelli sul tuo Mac e tiene il più forte che gira bene
.venv/bin/agency chrome-login x medium substack   # un login per piattaforma nel Chrome dell'agente
.venv/bin/agency run              # http://127.0.0.1:8765, oppure l'app "Agency" nel Dock
```

Parte in prova a secco (`dry_run: true`): produce tutto, non pubblica nulla. Quando la coda ti
convince: `dry_run: false`, poi accendi `publishing`; `approval_required` resta acceso finché non
decidi tu.

## I modelli su un SSD esterno

I modelli occupano circa 260 GB (il cervello da solo 95 GB: 44 GB di pesi che vanno in memoria e
una tabella n-gram da 50 GB che resta sul disco e viene letta mentre scrive). Il disco interno non
serve: tutti i modelli stanno in una sola cartella, che scegli una volta.

```bash
# 1. Utility Disco: inizializza l'SSD come APFS (GUID), chiamalo per esempio "AI" -> si monta in /Volumes/AI
# 2. spegni Spotlight su quel volume (altrimenti indicizza 260 GB):  sudo mdutil -i off /Volumes/AI
# 3. in .env:
AGENCY_MODELS=/Volumes/AI/models          # tutti i modelli e tutte le cache (llama.cpp, Hugging Face, LM Studio, ComfyUI)
AGENCY_ASSETS=/Volumes/AI/agency-assets   # facoltativo: anche video, immagini e voci generati
# 4. poi come sempre
scripts/download_models.sh
.venv/bin/agency doctor --benchmark       # mostra il disco, lo spazio libero e la velocità di lettura
```

Che SSD: un NVMe in un box Thunderbolt 4/5 o USB4 (2.000-6.000 MB/s), da 1 TB per avere spazio
anche per i video. Un SSD SATA su USB-A (circa 450 MB/s) va bene per immagini, video e voci ma non
per il cervello Flash-Next, che legge la sua tabella dal disco a ogni parola: `agency doctor`
misura la velocità e te lo dice; sotto circa 700 MB/s ti consiglia di tenere il cervello sul disco
interno o di usare il 27B. Gli altri modelli si caricano in memoria una volta per lavoro, quindi il
disco conta solo per il tempo di caricamento.

Se l'SSD è staccato i modelli semplicemente non ci sono: il doctor e la pagina Models dicono
"not mounted", nulla viene scaricato nel posto sbagliato, e l'agenzia continua a servire la
dashboard e la coda finché il disco non torna.

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
