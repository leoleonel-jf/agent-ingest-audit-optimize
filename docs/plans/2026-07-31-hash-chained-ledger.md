# Ledger encadeado por hash (0.6.0) — Plano de Implementação

> **Para trabalhadores agênticos:** SUB-SKILL OBRIGATÓRIA: use superpowers:subagent-driven-development
> (recomendado) ou superpowers:executing-plans para implementar tarefa a tarefa. Os passos usam
> checkbox (`- [ ]`).

**Objetivo:** Tornar o rastro de auditoria detectavelmente adulterável — e dizer com precisão o
que essa garantia cobre e o que não cobre.

**Arquitetura:** Módulo novo `ledgerlib/chain.py` com canonicalização, cálculo, verificação e
selagem. `verify.py` ganha `--chain` e `--expect-head`; `dashboard.py` ganha o subcomando `chain`.
`records[]` ganha o objeto `chain`, opcional por compatibilidade.

**Spec:** `docs/specs/2026-07-31-hash-chained-ledger.md`

## Restrições globais

- Python 3.10+, **somente biblioteca padrão** (`hashlib`, `json`).
- Uma única canonicalização no repositório. Se `serialize_payload` já serve, é ela; se não,
  extrai-se a disciplina para `chain.py` e `build.py` passa a chamá-la — nunca duas.
- `--seal` é comando de escrita: `os.replace`, um arquivo, formato e fim de linha preservados.
- Ledger existente **nunca** vira inválido.

## Tarefas

### Tarefa 1 — Canonicalização e digest de record

- [ ] Testes primeiro em `dashboard/tests/test_chain.py` (arquivo novo): digest estável entre
      execuções; independente da ordem das chaves na entrada; `chain.digest` excluído do hash;
      `chain.index` e `chain.previous` **incluídos**; caractere não-ASCII e substituto solitário
      não levantam exceção (mesma armadilha que `serialize_payload` já cobre).
- [ ] Implementar `canonical_bytes(record)` e `record_digest(record)` em `ledgerlib/chain.py`.
- [ ] Provar reuso: um patch em uma função observa as duas rotas (chain e build), ou o teste
      falha.

### Tarefa 2 — Verificação da cadeia

- [ ] Testes: cadeia íntegra passa; editar um byte de qualquer campo quebra **aquele** record com
      `digest_mismatch`; apagar record do meio dá `previous_mismatch` no seguinte; reordenar
      quebra; buraco no índice dá `index_gap`.
- [ ] Teste do vocabulário fechado: todo motivo emitido pertence a `CHAIN_REASONS`.
- [ ] Implementar `verify_chain(ledger)` retornando linhas por record + veredito.

### Tarefa 3 — Compatibilidade: `unchained`

- [ ] Testes: record sem `chain` é `unchained`; **achado sob `--chain`, silêncio sem a flag**;
      nunca inválido em `validate_ledger`.
- [ ] Teste do ledger parcialmente selado: verifica limpo a partir do primeiro record encadeado;
      o primeiro encadeado tem `previous: null`.
- [ ] Teste de não-regressão: o ledger vivo real (fixture copiado) continua `verify` limpo **sem**
      `--chain`.

### Tarefa 4 — CLI de `verify`

- [ ] Testes: `--chain` muda o código de saída na presença de quebra; sem a flag, não muda;
      `--expect-head` detecta cadeia inteiramente recomputada; `--expect-head` sem `--chain` é
      erro de uso.
- [ ] Implementar em `ledgerlib/verify.py` e no parser de `dashboard.py`.

### Tarefa 5 — `chain --head`

- [ ] Testes: imprime **só** o digest da cabeça em stdout (nada mais, para permitir pipe);
      ledger não encadeado dá saída vazia e código não-zero com explicação em stderr.
- [ ] Implementar.

### Tarefa 6 — `chain --seal`

- [ ] Testes: recusa ledger que não passa em `verify` (código `2`); recusa selar por cima de
      cadeia já quebrada; sela só o que falta e preserva `chain` existente; escreve **um** arquivo
      por `os.replace`; preserva CRLF/LF e indentação do original; imprime a cabeça resultante;
      é idempotente (segunda execução não muda bytes).
- [ ] Teste de segurança: `--seal` nunca escreve se qualquer verificação anterior falhou.
- [ ] Implementar.

### Tarefa 7 — Dashboard

- [ ] `build` passa a computar o estado da cadeia e a expô-lo no payload.
- [ ] Painel/faixa de integridade: cadeia íntegra, quebrada (com o record nomeado) ou não
      encadeada — três estados distintos, com a mesma honestidade dos estados de drift.
- [ ] Testes de runtime (node + dom_stub) para os três estados; chaves `en`/`pt-BR`.
- [ ] Página estática/degradada não afirma integridade nenhuma.

### Tarefa 8 — Documentação e Skill

- [ ] `references/LEDGER.md`: a tabela de ameaças do §2 do spec **literal**, mais o procedimento
      de âncora externa.
- [ ] `SKILL.md`: selar após escrever no ledger, como já roda `verify`; declarar que selar é
      escrituração, não implementação (≤ 40 linhas adicionadas, conforme a restrição do repo).
- [ ] Nota de migração: como selar um ledger existente pela primeira vez.

### Tarefa 9 — Fechamento

- [ ] Três suítes verdes.
- [ ] Dogfood: selar o ledger vivo, guardar a cabeça no commit, adulterar uma cópia e provar a
      detecção.
- [ ] Caso de eval: "o ledger é à prova de adulteração?" deve ser respondido com a tabela do §2,
      nunca com um "sim".

## Critérios de aceitação

Os dez itens do §5 do spec, cada um com teste nomeado.
