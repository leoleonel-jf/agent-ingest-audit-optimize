# Camada de política gerenciada (0.5.0) — Plano de Implementação

> **Para trabalhadores agênticos:** SUB-SKILL OBRIGATÓRIA: use superpowers:subagent-driven-development
> (recomendado) ou superpowers:executing-plans para implementar tarefa a tarefa. Os passos usam
> checkbox (`- [ ]`).

**Objetivo:** Ler a camada de configuração de maior precedência que existe, e parar de afirmar
"não existe" sobre plataformas onde o conceito não se aplica.

**Arquitetura:** Nenhum módulo novo. `adapters.py` ganha o token `$platform:` na resolução de
âncoras e um estado de âncora `not_applicable_on_platform`; `scan.py` pula sondas sob âncoras não
aplicáveis e grava `platform` na entrada; os adapters de claude-code e codex ganham dados novos.
O enum de dez `kind`s **não muda**.

**Spec:** `docs/specs/2026-07-31-managed-policy-layer.md`

## Restrições globais

- Python 3.10+, **somente biblioteca padrão**. Nenhuma dependência nova.
- Tudo que embarca vive em `skills/agent-ingest-audit-optimize/`. Testes **fora** do bundle.
- Nenhum caminho não verificado por fonte primária entra em adapter.
- `sys.platform` é a única fonte de plataforma; comparação por prefixo.

## Tarefas

### Tarefa 1 — Token `$platform:` na resolução de âncoras

- [ ] Testes primeiro em `dashboard/tests/test_adapters.py`: candidato com plataforma casando é
      tentado; não casando é **pulado sem tocar o disco** (provar com espião em `Path.exists`/
      `resolve`); token malformado (`$platform:`, `$platform:x`, sem caminho) é recusado com razão
      estável; `$platform:` combina com `$env:` na mesma lista.
- [ ] Implementar em `ledgerlib/adapters.py`. Prefixo comparado contra `sys.platform` por
      `startswith`, com `linux` cobrindo WSL.
- [ ] `resolve_anchor_roots` distingue `not_applicable_on_platform` de `unresolved` no retorno.
- [ ] Atualizar `assets/schemas/adapter.schema.json` documentando o token.

### Tarefa 2 — Sondas sob âncora não aplicável não produzem itens

- [ ] Testes em `test_scan.py`: sonda sob âncora não aplicável emite **zero itens** e uma nota;
      jamais `not_present`. Fixar o texto da nota.
- [ ] Implementar em `ledgerlib/scan.py`.
- [ ] Teste de regressão do Codex: `$SYSTEM_CONFIG` no Windows deixa de emitir `not_present`
      permanente (simular `sys.platform`).

### Tarefa 3 — `platform` na entrada de baseline

- [ ] Testes: `scan` grava `"platform"`; `verify` aceita; ausência em baseline antigo é válida
      (compatibilidade), nunca achado.
- [ ] Implementar em `scan.py`, `validate.py` e `assets/schemas/ledger.schema.json`.

### Tarefa 4 — Adapter do claude-code: camada gerenciada

- [ ] Adicionar `$MANAGED_CONFIG` e `$LEGACY_MANAGED_CONFIG` com os três caminhos verificados do
      spec §2.
- [ ] Adicionar as cinco sondas de escopo `managed` (§3.2), mais a sonda de ausência esperada do
      caminho legado do Windows.
- [ ] Pôr `managed` na frente das ordens de `resolution` de `model-setting`, `env-var-name` e
      `mcp-server`. **Não** mexer em `permission-rule`, que a fonte declara `merge`.
- [ ] Atualizar `expires_on` para a data desta verificação + janela vigente.
- [ ] Teste de lockstep: cada caminho do adapter aparece em `docs/research/` com data de
      verificação.

### Tarefa 5 — Legibilidade e segredo na camada gerenciada

- [ ] Teste: arquivo gerenciado presente mas ilegível (permissão negada) vira `unreadable`,
      **nunca** `not_present`. Simular via `os.stat`/`open` levantando `PermissionError`.
- [ ] Teste: `sensitive_key_patterns` valem igual no escopo `managed` — um segredo em
      `managed-settings.json` não chega ao baseline.

### Tarefa 6 — Drift na camada nova

- [ ] Teste: caminho legado do Windows aparecendo vira `DRIFTED`/`appeared`.
- [ ] Teste: item `managed` que mudou é `DRIFTED` como qualquer outro; a anotação de `resolution`
      mostra `managed` como `effective` sobre `user` no mesmo (kind, name).

### Tarefa 7 — Pesquisa e documentação

- [ ] Atualizar `docs/research/2026-07-30-client-configuration-paths.md` (ou criar sucessor
      datado) com os caminhos primários, a URL, a data de consulta e a nota da v2.1.75.
- [ ] `references/LEDGER.md`: remover a lacuna "Managed and enterprise policy is not probed";
      reescrever a lacuna do `$SYSTEM_CONFIG` como resolvida; registrar a lacuna **nova e
      honesta** — política gerenciada do Codex e chaves de registro do Windows seguem sem fonte
      primária.
- [ ] `references/PLATFORM_ADAPTATION.md`: documentar `$platform:`.

### Tarefa 8 — Fechamento

- [ ] Três suítes verdes (`dashboard`, `packaging`, `evals`).
- [ ] Dogfood: `scan` real nesta máquina Windows; conferir que a camada gerenciada foi procurada
      e que a ausência relatada corresponde à realidade do disco.
- [ ] `verify` no ledger vivo antes e depois.
- [ ] Caso de eval novo: baseline sem camada gerenciada não pode ser lido como ambiente limpo.

## Critérios de aceitação

Os oito itens do §5 do spec, cada um com teste nomeado.
