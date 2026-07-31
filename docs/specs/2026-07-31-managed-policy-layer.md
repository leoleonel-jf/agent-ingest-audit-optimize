# A camada de política gerenciada (0.5.0)

Status: PROPOSTO 2026-07-31 — aguarda deliberação
Target version: 0.5.0
Fecha: lacuna nº 1 de `references/LEDGER.md` ("Managed and enterprise policy is not probed") e a
lacuna do `$SYSTEM_CONFIG` POSIX-only

## 1. O problema

Política gerenciada é a camada de **maior precedência** que existe: ela sobrepõe linha de
comando, projeto e usuário, e o usuário não pode sobrescrevê-la. Um baseline que não a lê está
incompleto exatamente na camada que decide o resultado de todas as outras.

A razão de não ter sido sondada até aqui está registrada e continua válida: a pesquisa de
2026-07-30 só dizia "platform-specific policy directory", e o projeto não embarca caminho não
verificado. **Essa razão caducou** — os caminhos abaixo vêm da documentação primária atual.

## 2. Evidência primária

Fonte: `https://code.claude.com/docs/en/settings`, consultada em 2026-07-31.

| Plataforma | Arquivo | Diretório de fragmentos |
|---|---|---|
| macOS | `/Library/Application Support/ClaudeCode/managed-settings.json` | `.../managed-settings.d/` |
| Linux e WSL | `/etc/claude-code/managed-settings.json` | `/etc/claude-code/managed-settings.d/` |
| Windows | `C:\Program Files\ClaudeCode\managed-settings.json` | `C:\Program Files\ClaudeCode\managed-settings.d\` |

Precedência declarada: **managed** (maior) → argumentos de linha de comando → local → projeto →
usuário. Exceção declarada: **regras de permissão fazem merge entre escopos**, não override.

Um fato do changelog que vira sonda: o caminho legado do Windows
`C:\ProgramData\ClaudeCode\managed-settings.json` **deixou de ser suportado na v2.1.75**. Um
arquivo ainda presente ali é política morta que o administrador provavelmente pensa estar ativa —
é achado, não ruído. Ele é sondado como **ausência esperada**.

**Lacuna honesta:** não há verificação primária equivalente para política gerenciada do Codex
nesta passagem. O adapter do Codex mantém apenas `$SYSTEM_CONFIG` (`/etc/codex`) como hoje, e a
sonda de política gerenciada do Codex fica registrada como pendente de pesquisa própria. Não se
inventa caminho.

## 3. Desenho

### 3.1 Âncora nova, com guarda de plataforma

`$MANAGED_CONFIG` entra no adapter do claude-code. O formato de âncora hoje é uma lista de
candidatos tentados em ordem, e já tem precedente de token tipado (`$env:NOME`). A extensão
mínima e consistente é um segundo token, `$platform:<sys>:<caminho>`:

```json
"$MANAGED_CONFIG": [
  "$platform:darwin:/Library/Application Support/ClaudeCode",
  "$platform:linux:/etc/claude-code",
  "$platform:win32:C:/Program Files/ClaudeCode"
]
```

Um candidato cuja plataforma não casa é **pulado**, não testado no disco. Se todos forem pulados,
a âncora fica `not_applicable_on_platform` — estado distinto de `unresolved`, e essa distinção é
o conserto do `$SYSTEM_CONFIG`: hoje ele fica permanentemente irresolvido no Windows e suas
sondas permanentemente `not_present`, o que afirma "olhamos e não havia" sobre uma plataforma
onde o conceito não existe.

`sys.platform` é a fonte, comparado por prefixo (`linux`, `darwin`, `win32`), com WSL contando
como `linux` — que é o que o próprio cliente faz.

### 3.2 Sondas sob a âncora nova

Nenhum `kind` novo. A política gerenciada carrega os mesmos tipos que já existem, no escopo novo
`managed`:

```json
{ "kind": "model-setting",   "scope": "managed", "path": "$MANAGED_CONFIG/managed-settings.json" },
{ "kind": "permission-rule", "scope": "managed", "path": "$MANAGED_CONFIG/managed-settings.json",
  "parse": "json", "pointer": "/permissions" },
{ "kind": "hook",            "scope": "managed", "path": "$MANAGED_CONFIG/managed-settings.json",
  "parse": "json", "pointer": "/hooks" },
{ "kind": "env-var-name",    "scope": "managed", "path": "$MANAGED_CONFIG/managed-settings.json",
  "parse": "json", "pointer": "/env" },
{ "kind": "model-setting",   "scope": "managed", "glob": "$MANAGED_CONFIG/managed-settings.d/*.json" }
```

Manter o enum de dez `kind`s fechado é deliberado: a política gerenciada não é um tipo novo de
coisa, é a mesma coisa numa camada mais alta.

### 3.3 Precedência declarada

As ordens de `resolution` do adapter ganham `managed` na frente:

```json
"model-setting": { "mode": "key-override", "order": ["managed", "project", "user"] },
"env-var-name":  { "mode": "key-override", "order": ["managed", "project", "user"] },
"mcp-server":    { "mode": "override",     "order": ["managed", "project", "user"] }
```

`permission-rule` continua `merge` — a documentação primária declara merge explicitamente, e
declarar override ali seria contrariar a fonte.

### 3.4 Política legada como ausência esperada

```json
{ "kind": "model-setting", "scope": "managed",
  "path": "$LEGACY_MANAGED_CONFIG/managed-settings.json" }
```

com `$LEGACY_MANAGED_CONFIG` guardado por `$platform:win32:C:/ProgramData/ClaudeCode`. O baseline
grava `not_present` quando está limpo; `drift` classifica o aparecimento como `DRIFTED`/`appeared`,
que é a leitura correta — política morta ressuscitada.

### 3.5 Permissões de leitura

`/Library/Application Support`, `/etc` e `C:\Program Files` podem ser ilegíveis para o usuário
comum. Isso já tem vocabulário: `unreadable`. O que **não** pode acontecer é degradar para
`not_present`, que afirmaria ausência onde houve recusa de leitura. Um teste fixa exatamente isso.

### 3.6 `platform` no baseline

A entrada de baseline passa a gravar `"platform": "win32"`. Sem isso, dois baselines da mesma
máquina lógica em plataformas diferentes parecem divergir sem explicação, e `drift` não tem como
dizer que a diferença é estrutural, não desvio.

## 4. O que isto não faz

- Não lê política gerenciada do Codex (sem fonte primária nesta passagem).
- Não lê chaves de política do registro do Windows, que a pesquisa de 2026-07-30 menciona sem
  caminho verificado.
- Não computa vencedor de precedência: `scan` grava a camada, `drift` anota; calcular quem vence
  segue fora de `classify_item`, como o §3.2 do spec de drift exige.
- Não sonda credenciais nem digere script de hook — são itens separados do mesmo 0.5.0.

## 5. Aceitação

1. `$platform:` pulado por não-correspondência, sem tocar o disco; âncora sem candidato aplicável
   vira `not_applicable_on_platform`, distinto de `unresolved`.
2. Sondas sob âncora não aplicável **não produzem itens** e produzem uma nota — nunca
   `not_present`.
3. `$SYSTEM_CONFIG` do Codex no Windows deixa de emitir `not_present` permanente.
4. `managed-settings.json` ilegível vira `unreadable`, jamais `not_present`.
5. Redação vale igual na camada gerenciada (mesmos `sensitive_key_patterns`).
6. Entrada de baseline grava `platform`; `verify` aceita e o schema documenta.
7. Caminho legado do Windows sondado como ausência esperada; aparecimento vira `DRIFTED`.
8. Suítes verdes; `expires_on` do adapter revisado com a data desta verificação.
