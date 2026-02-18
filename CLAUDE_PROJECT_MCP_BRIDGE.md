# Claude CLI MCP Bridge — Progetto Claude CLI

## Obiettivo

Costruire un MCP server remoto che espone Claude Code CLI come tool richiamabile da claude.ai (o qualsiasi MCP client). Questo permette di lanciare comandi, build, test, e task di coding sul proprio server Ubuntu remoto direttamente dalla chat web di Claude.

## Caso d'uso concreto

Tommy lavora su claude.ai (web/mobile) e vuole poter dire:
- "Esegui i test del progetto scan2step sul mio server"
- "Fai un git pull e rebuilda il progetto"
- "Controlla lo stato della GPU e la VRAM disponibile"
- "Crea un nuovo branch e implementa questa feature"

Claude.ai chiama il tool MCP → il bridge sul server Ubuntu riceve la richiesta → esegue `claude` CLI in subprocess → restituisce il risultato nella chat web.

## Architettura

```
┌──────────────────────────────────────────────────────────┐
│                    claude.ai (web)                        │
│                                                          │
│  Impostazioni → Integrazioni → Aggiungi connettore       │
│  URL: https://mcp.tommy.ts.net                           │
└──────────────┬───────────────────────────────────────────┘
               │ HTTPS (Streamable HTTP / MCP protocol)
               │
┌──────────────▼───────────────────────────────────────────┐
│           Tailscale Funnel (o Cloudflare Tunnel)          │
│           https://mcp.tommy.ts.net → localhost:8787       │
└──────────────┬───────────────────────────────────────────┘
               │
┌──────────────▼───────────────────────────────────────────┐
│           MCP Bridge Server (FastAPI + mcp SDK)           │
│           porta: 8787                                     │
│                                                          │
│  ┌─────────────────────────────────────────────────────┐ │
│  │  Tools esposti:                                     │ │
│  │                                                     │ │
│  │  • claude_execute  — esegui prompt via claude CLI    │ │
│  │  • run_command     — bash command diretto            │ │
│  │  • file_read       — leggi file dal server           │ │
│  │  • file_write      — scrivi file sul server          │ │
│  │  • gpu_status      — nvidia-smi / VRAM               │ │
│  │  • project_status  — git status, log, diff           │ │
│  │  • system_info     — uptime, disk, memory            │ │
│  └─────────────────────────────────────────────────────┘ │
│                                                          │
│  ┌─────────────────────────────────────────────────────┐ │
│  │  Sicurezza:                                         │ │
│  │  • Bearer token (API key generata al setup)          │ │
│  │  • Whitelist directory (sandbox)                     │ │
│  │  • Rate limiting                                    │ │
│  │  • Audit log di ogni invocazione                    │ │
│  │  • Timeout per ogni operazione                      │ │
│  └─────────────────────────────────────────────────────┘ │
└──────────────┬───────────────────────────────────────────┘
               │ subprocess
┌──────────────▼───────────────────────────────────────────┐
│           Server Ubuntu 24 (RTX 3090)                     │
│                                                          │
│  • claude CLI (installato via npm)                       │
│  • Workspace: ~/projects/                                │
│  • Tailscale VPN attiva                                  │
│  • GPU: Nvidia RTX 3090 24GB                             │
└──────────────────────────────────────────────────────────┘
```

## Contesto tecnico

### Infrastruttura di Tommy

- Server Ubuntu 24 con Nvidia RTX 3090 (24GB VRAM)
- Tailscale VPN attiva su più dispositivi
- Claude CLI installato (Anthropic Max subscription)
- Progetti in ~/projects/ (scan2step, native-research, ecc.)

### Protocollo MCP

- Specifica: https://spec.modelcontextprotocol.io/
- Transport: **Streamable HTTP** (richiesto per remote MCP con claude.ai)
- SDK Python: `mcp` (pip install mcp)
- Il server deve implementare: tool discovery, tool invocation, lifecycle events
- JSON-RPC 2.0 over HTTP

### Come claude.ai si connette

1. Impostazioni → Integrazioni → Aggiungi connettore personalizzato
2. Inserire URL del server MCP (es. `https://mcp.tommy.ts.net`)
3. Claude.ai scopre i tool disponibili e li usa quando rilevante
4. Richiede piano Max, Team o Enterprise

### Tailscale Funnel

Tailscale Funnel espone un servizio locale su un URL HTTPS pubblico senza aprire porte sul router:

```bash
# Abilitare Funnel (una tantum)
tailscale funnel --bg 8787
# Risultato: https://<hostname>.ts.net → localhost:8787
```

Alternativa: Cloudflare Tunnel (`cloudflared tunnel`).

## Stack tecnologico

- **Linguaggio**: Python 3.11+
- **Framework HTTP**: FastAPI (per il transport MCP Streamable HTTP)
- **MCP SDK**: `mcp` (official Python SDK)
- **Subprocess**: `asyncio.create_subprocess_exec` per claude CLI
- **Auth**: Bearer token in header Authorization
- **Logging**: structlog (JSON structured)
- **Process manager**: systemd unit per il servizio
- **Package manager**: uv (non pip/poetry)
- **Tunnel**: Tailscale Funnel (primario) o Cloudflare Tunnel (fallback)

## Struttura progetto

```
claude-mcp-bridge/
├── pyproject.toml
├── README.md
├── .env.example              # BEARER_TOKEN, ALLOWED_DIRS, etc.
├── .env                      # (gitignored) configurazione reale
├── src/
│   └── mcp_bridge/
│       ├── __init__.py
│       ├── server.py          # Entry point FastAPI + MCP server setup
│       ├── auth.py            # Middleware autenticazione Bearer token
│       ├── tools/
│       │   ├── __init__.py
│       │   ├── claude_execute.py   # Tool: esegui prompt via claude CLI
│       │   ├── run_command.py      # Tool: esegui comando bash (sandboxed)
│       │   ├── file_ops.py         # Tool: read/write file (sandboxed)
│       │   ├── gpu_status.py       # Tool: nvidia-smi parser
│       │   ├── project_status.py   # Tool: git status/log/diff
│       │   └── system_info.py      # Tool: uptime, disk, memory
│       ├── sandbox.py         # Path validation, whitelist enforcement
│       ├── rate_limiter.py    # Rate limiting per-tool
│       ├── audit.py           # Audit log di ogni invocazione
│       └── config.py          # Configurazione da .env
├── systemd/
│   └── mcp-bridge.service     # Unit systemd per autostart
├── scripts/
│   ├── setup.sh               # Setup iniziale (genera token, configura Funnel)
│   └── test_connection.sh     # Verifica che il bridge sia raggiungibile
└── tests/
    ├── test_tools.py
    ├── test_auth.py
    └── test_sandbox.py
```

## Dettaglio dei tools MCP

### Tool 1: `claude_execute`

Il tool principale. Invia un prompt a Claude CLI e restituisce il risultato.

```python
@mcp_server.tool()
async def claude_execute(
    prompt: str,
    working_directory: str = "~/projects",
    max_turns: int = 5,
    timeout_seconds: int = 300
) -> str:
    """
    Esegue un prompt tramite Claude Code CLI sul server remoto.
    
    Claude CLI ha accesso al filesystem, può leggere/scrivere file,
    eseguire comandi, e completare task di coding complessi.
    
    Args:
        prompt: Il prompt/istruzione da eseguire
        working_directory: Directory di lavoro (deve essere in whitelist)
        max_turns: Numero massimo di turni agentic (default 5)
        timeout_seconds: Timeout globale in secondi (default 300)
    """
    # Validare working_directory contro whitelist
    # Eseguire: claude --print --dangerously-skip-permissions --max-turns N -p "prompt"
    # Catturare stdout/stderr
    # Restituire risultato con metadata (tempo, exit code, etc.)
```

**Flags Claude CLI importanti:**
- `--print` / `-p`: modalità non-interattiva, stampa risultato e esce
- `--dangerously-skip-permissions`: salta conferme (necessario per automazione)
- `--max-turns N`: limita i turni agentic
- `--output-format json`: output strutturato
- `--model`: possibilità di specificare il modello (sonnet vs opus)

### Tool 2: `run_command`

Esecuzione diretta di comandi bash, più leggero di claude_execute per operazioni semplici.

```python
@mcp_server.tool()
async def run_command(
    command: str,
    working_directory: str = "~/projects",
    timeout_seconds: int = 60
) -> str:
    """
    Esegue un comando bash sul server remoto.
    
    Per operazioni semplici (build, test, git, status checks).
    Per task complessi che richiedono ragionamento, usa claude_execute.
    
    Args:
        command: Comando bash da eseguire
        working_directory: Directory di lavoro
        timeout_seconds: Timeout in secondi
    """
    # Validare command contro blocklist (rm -rf /, shutdown, etc.)
    # Validare working_directory
    # Eseguire con asyncio.create_subprocess_shell
    # Restituire stdout + stderr + exit code
```

### Tool 3: `file_read` / `file_write`

```python
@mcp_server.tool()
async def file_read(path: str, line_range: str | None = None) -> str:
    """Legge un file dal server. Path deve essere in whitelist."""

@mcp_server.tool()
async def file_write(path: str, content: str, mode: str = "overwrite") -> str:
    """Scrive un file sul server. mode: 'overwrite' | 'append'. Path in whitelist."""
```

### Tool 4: `gpu_status`

```python
@mcp_server.tool()
async def gpu_status() -> str:
    """
    Restituisce lo stato della GPU: modello, VRAM totale/usata/libera,
    temperatura, processi attivi, utilizzo.
    Parsing di nvidia-smi --query-gpu=...
    """
```

### Tool 5: `project_status`

```python
@mcp_server.tool()
async def project_status(
    project_path: str,
    include_diff: bool = False,
    log_count: int = 5
) -> str:
    """
    Stato di un progetto git: branch corrente, status, ultimi N commit,
    opzionalmente diff delle modifiche non committed.
    """
```

### Tool 6: `system_info`

```python
@mcp_server.tool()
async def system_info() -> str:
    """
    Info di sistema: uptime, CPU load, RAM usata/totale, disco,
    temperatura CPU/GPU, processi principali.
    """
```

## Sicurezza — CRITICA

Questo server espone l'esecuzione di comandi su un server reale. La sicurezza è priorità assoluta.

### Autenticazione

- Bearer token generato al setup (32+ bytes random, base64)
- Verificato su ogni richiesta MCP via middleware
- Token in .env, MAI nel codice o nei log

```python
# auth.py
async def verify_bearer_token(request: Request) -> bool:
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(401)
    token = auth_header[7:]
    if not hmac.compare_digest(token, config.BEARER_TOKEN):
        raise HTTPException(403)
```

### Sandbox filesystem

- **ALLOWED_DIRS**: lista di directory accessibili (default: `~/projects`)
- Ogni path viene risolto a path assoluto e verificato che sia sotto una ALLOWED_DIR
- Nessun accesso a `/etc`, `/root`, `/var`, directory di sistema
- Symlink risolti prima della verifica (no escape via symlink)

### Blocklist comandi

- Comandi proibiti in `run_command`: `rm -rf /`, `shutdown`, `reboot`, `mkfs`, 
  `dd if=`, `:(){ :|:& };:`, `chmod 777 /`, etc.
- Regex pattern matching, non semplice string match
- `claude_execute` è meno restrittivo perché Claude CLI ha i suoi guardrail

### Rate limiting

- Max 10 richieste/minuto per tool
- Max 3 `claude_execute` concorrenti (ogni istanza usa VRAM e CPU)
- Cooldown dopo errori ripetuti

### Audit log

- Ogni invocazione logata con: timestamp, tool, parametri, risultato (troncato), durata, IP
- Log in file JSON rotato (structlog)
- Opzionale: webhook/notifica su operazioni sensibili

### Timeout

- Ogni operazione ha un timeout configurabile
- `claude_execute`: default 300s (5 min), max 600s
- `run_command`: default 60s, max 300s
- `file_read/write`: default 10s
- Kill del processo se timeout raggiunto

## Configurazione (.env)

```bash
# Token di autenticazione (generato da setup.sh)
BEARER_TOKEN=your-random-token-here

# Directory accessibili (comma-separated)
ALLOWED_DIRS=~/projects,~/documents

# Comandi bloccati (regex, comma-separated) 
BLOCKED_COMMANDS=rm\s+-rf\s+/,shutdown,reboot,mkfs,dd\s+if=

# Rate limits
MAX_REQUESTS_PER_MINUTE=10
MAX_CONCURRENT_CLAUDE=3

# Claude CLI
CLAUDE_CLI_PATH=claude
CLAUDE_DEFAULT_MODEL=sonnet

# Server
HOST=127.0.0.1
PORT=8787
LOG_LEVEL=info
LOG_FILE=~/.local/share/mcp-bridge/audit.log

# Tunnel (opzionale, per setup automatico)
TUNNEL_TYPE=tailscale  # tailscale | cloudflare
```

## Setup e deployment

### Script setup.sh

```bash
#!/bin/bash
# 1. Genera Bearer token
TOKEN=$(openssl rand -base64 32)
echo "BEARER_TOKEN=$TOKEN" >> .env

# 2. Installa dipendenze
uv sync

# 3. Verifica claude CLI
claude --version || echo "ERRORE: claude CLI non trovato"

# 4. Configura Tailscale Funnel
tailscale funnel --bg 8787
echo "URL pubblico: https://$(tailscale status --json | jq -r '.Self.DNSName' | sed 's/\.$//')"

# 5. Installa systemd unit
sudo cp systemd/mcp-bridge.service /etc/systemd/system/
sudo systemctl enable mcp-bridge
sudo systemctl start mcp-bridge

# 6. Stampa istruzioni per claude.ai
echo ""
echo "=== SETUP COMPLETATO ==="
echo "1. Vai su claude.ai → Impostazioni → Integrazioni"
echo "2. Aggiungi connettore personalizzato"
echo "3. URL: https://$(tailscale status --json | jq -r '.Self.DNSName' | sed 's/\.$//')"
echo "4. Header Authorization: Bearer $TOKEN"
```

### systemd unit

```ini
[Unit]
Description=Claude MCP Bridge Server
After=network.target tailscaled.service

[Service]
Type=simple
User=tommy
WorkingDirectory=/home/tommy/projects/claude-mcp-bridge
ExecStart=/home/tommy/.local/bin/uv run python -m mcp_bridge.server
Restart=always
RestartSec=5
Environment=PATH=/home/tommy/.local/bin:/usr/local/bin:/usr/bin:/bin

[Install]
WantedBy=multi-user.target
```

## Priorità di implementazione

1. **MVP**: server FastAPI + tool `claude_execute` + auth Bearer + sandbox base → funziona end-to-end
2. **v0.2**: aggiungere `run_command`, `file_ops`, `gpu_status` + rate limiting
3. **v0.3**: `project_status`, `system_info` + audit log completo + systemd unit
4. **v0.4**: setup.sh automatico, test suite, documentazione, health check endpoint

## Vincoli

- Python 3.11+ con type hints ovunque
- Package manager: **uv** (non pip, non poetry)
- Zero dipendenze da servizi cloud (tutto self-hosted)
- Il bridge NON deve mai loggare il contenuto completo delle risposte (troncamento)
- Il bridge NON deve mai esporre il Bearer token nei log
- Il codice deve funzionare anche senza GPU (i tool GPU restituiscono "N/A")
- Licenza: MIT
- Il server deve restare stabile per giorni senza restart (no memory leak)

## Dipendenze Python

```toml
[project]
dependencies = [
    "fastapi>=0.115",
    "uvicorn>=0.32",
    "mcp>=1.0",           # Official MCP Python SDK
    "structlog>=24.0",
    "python-dotenv>=1.0",
    "pydantic>=2.0",
    "pydantic-settings>=2.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.24",
    "httpx>=0.27",        # Per test client
]
```

## Note aggiuntive

- Claude CLI in modalità `--print` è "one-shot": esegue e esce. Non mantiene stato tra invocazioni.
- Per task lunghi, considerare di salvare lo stato in un file nel workspace e riprenderlo alla chiamata successiva.
- Il flag `--dangerously-skip-permissions` è necessario per l'automazione ma va usato SOLO nel contesto del bridge con le protezioni sandbox attive.
- Se Tailscale Funnel non è disponibile (richiede piano specifico), Cloudflare Tunnel è l'alternativa gratuita.
- Il server MCP deve gestire correttamente la disconnessione del client (cleanup processi orfani).
- Testare che claude.ai riesca a fare discovery dei tool: il server deve rispondere correttamente a `tools/list`.

## Riferimenti

- MCP Spec: https://spec.modelcontextprotocol.io/
- MCP Python SDK: https://github.com/modelcontextprotocol/python-sdk
- Claude Code docs (MCP): https://code.claude.com/docs/en/mcp
- Tailscale Funnel: https://tailscale.com/kb/1223/funnel
- Cloudflare Tunnel: https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/
- steipete/claude-code-mcp (riferimento): https://github.com/steipete/claude-code-mcp
- Claude CLI flags: https://code.claude.com/docs/en/cli-reference
