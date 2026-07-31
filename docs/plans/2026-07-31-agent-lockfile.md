# `agent.lock` (0.7.0, incremento 1) — Plano de Implementação

> **Para trabalhadores agênticos:** SUB-SKILL OBRIGATÓRIA: superpowers:subagent-driven-development
> ou superpowers:executing-plans. Passos com checkbox (`- [ ]`).

**Objetivo:** Transformar um baseline (observação) num lockfile (intenção declarada) que uma
passagem de CI compara e reprova.

**Arquitetura:** Módulo novo `ledgerlib/lock.py`. Canonicalização reusa `chain.canonical_text`.
Escrita atômica reusa o idioma de `chain._write_atomically`. `lockable` é campo novo de probe no
adapter. Subcomando `lock` em `dashboard.py`.

**Spec:** `docs/specs/2026-07-31-agent-lockfile.md`

## Restrições globais

- Python 3.10+, **somente biblioteca padrão**.
- **Uma canonicalização** no repositório: `chain.canonical_text`. Não escrever outra.
- `--check` **não toca o sistema de arquivos** além de ler o ledger e o lockfile.
- Determinismo é requisito, não qualidade: sem timestamp, sem caminho absoluto no arquivo.

## Tarefas

### Tarefa 1 — `lockable` no adapter

- [ ] Testes em `test_adapters.py`: probe com `"lockable": true` valida; valor não-booleano é
      achado; ausência é `false` por omissão (compatibilidade com adapters existentes).
- [ ] Implementar em `_validate_probe` e documentar em `adapter.schema.json`.
- [ ] Marcar `lockable` nos probes de `skill`, `plugin`, `mcp-server`, `agent`, `command`, `hook`
      dos adapters claude-code e codex. **Não** marcar os quatro de configuração (§2.3 do spec).
- [ ] Teste de lockstep: o conjunto de kinds lockable embarcado é exatamente o do spec.

### Tarefa 2 — Construir o lockfile

- [ ] Testes em `dashboard/tests/test_lock.py` (novo): duas chamadas sobre o mesmo baseline dão
      **bytes idênticos**; a ordem de `entries` independe da ordem de entrada; só kinds lockable
      entram; `client`, `adapter_version` e `platform` vêm do baseline.
- [ ] Teste do determinismo entre plataformas: nenhum caminho absoluto e nenhum timestamp no
      arquivo (grep sobre a saída).
- [ ] Implementar `build_lock(ledger, baseline_id, adapter)` em `ledgerlib/lock.py`.
- [ ] Teste: baseline inexistente levanta `LedgerError`.

### Tarefa 3 — `--check`

- [ ] Testes por caso do vocabulário: `added`, `removed`, `changed`, `state_changed` — cada um
      isolado, cada um nomeando a entrada.
- [ ] Teste: lockfile idêntico ao baseline produz zero divergências.
- [ ] **Teste de não-acesso:** espião sobre `resolve_anchored`/`Path.open` prova que `--check`
      não abre nenhum arquivo do ambiente.
- [ ] Teste: `client` ou `platform` diferente é achado explícito, não comparação silenciosa.
- [ ] Teste: `lock_version` desconhecida é erro de ferramenta.
- [ ] Implementar `check_lock`.

### Tarefa 4 — CLI

- [ ] Testes por `dashboard.main`, nunca pela função interna (a regra que `test_scan.py` já
      registra): `--from` escreve; `--check` compara; os dois juntos é erro de uso; nenhum dos
      dois é erro de uso.
- [ ] Códigos de saída: `0` idêntico, `1` divergência, `2` erro de ferramenta.
- [ ] `--out` recusa sobrescrever arquivo que não parece um `agent.lock` sem `--force`; teste do
      arquivo alheio preservado.
- [ ] Implementar `lock_command` e a fiação argparse.

### Tarefa 5 — Documentação

- [ ] `references/LEDGER.md`: seção "Pinning the supply chain" — o que o lockfile é, por que não
      é o baseline, e por que `--check` não lê o disco.
- [ ] `README.md`: os dois comandos, e a linha de CI.
- [ ] `SKILL.md` (≤ 40 linhas): quando oferecer `lock`, e que ele **não** substitui `drift`.

### Tarefa 6 — Fechamento

- [ ] Três suítes verdes.
- [ ] Dogfood: gerar `agent.lock` do baseline real desta máquina; conferir determinismo rodando
      duas vezes; adulterar uma entrada e provar que `--check` reprova nomeando-a.
- [ ] `verify --chain` no ledger vivo antes e depois.
- [ ] Caso de eval: pedir "meu ambiente está seguro?" não pode ser respondido com um lockfile
      verde — ele diz que nada mudou desde o pin, não que o que foi pinado é confiável.

## Critérios de aceitação

Os oito itens do §3 do spec, cada um com teste nomeado.
