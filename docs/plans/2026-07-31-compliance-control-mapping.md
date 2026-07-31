# Mapeamento de controles de conformidade (0.7.0) — Plano de Implementação

> **Para trabalhadores agênticos:** SUB-SKILL OBRIGATÓRIA: use superpowers:subagent-driven-development
> (recomendado) ou superpowers:executing-plans para implementar tarefa a tarefa. Os passos usam
> checkbox (`- [ ]`).

**Objetivo:** Traduzir record → controle regulatório, inventariando evidência **sem jamais
afirmar conformidade**.

**Arquitetura:** Módulo novo `ledgerlib/compliance.py` (carregar mapeamento, avaliar predicado,
montar relatório, escrever pacote). Dados novos em `assets/compliance/*.json` com schema próprio,
espelhando exatamente como adapters já funcionam. Subcomando `compliance` em `dashboard.py`.

**Spec:** `docs/specs/2026-07-31-compliance-control-mapping.md`

## Restrições globais

- Python 3.10+, **somente biblioteca padrão**.
- **Nenhuma string de mapeamento é executada, avaliada ou interpolada.** O predicado é uma
  estrutura de dados fechada, lida por código próprio. Mapeamento é conteúdo.
- A palavra "compliant" (e equivalentes que afirmem conformidade) não aparece em nenhuma saída.
  Um teste faz grep disso na fonte e no render.
- Um framework por arquivo: adicionar framework não pode exigir mudança de código.

## Tarefas

### Tarefa 1 — Schema e carregamento de mapeamento

- [ ] Escrever `assets/schemas/compliance.schema.json`.
- [ ] Testes primeiro em `dashboard/tests/test_compliance.py`: mapeamento válido carrega;
      inválido, desconhecido e **vencido** (`expires_on` no passado) são erro de ferramenta (`2`),
      cada um com mensagem distinta; `verified_on` e `source` são obrigatórios.
- [ ] Implementar `load_mapping` em `ledgerlib/compliance.py`, reusando a disciplina de validação
      dos adapters.

### Tarefa 2 — O avaliador de predicado

- [ ] Testes por operador: `min_count`, `where`, `every`, `field` (com caminho pontilhado como
      `authorization.quote`), `non_empty`. Coleção ausente, campo ausente, tipo errado — cada um
      degrada para `EVIDENCE_ABSENT` com motivo, **nunca** exceção.
- [ ] Teste de segurança: um mapeamento contendo `__import__`, `{{}}`, `${}` ou similar num campo
      de string é tratado como texto literal e nada é executado.
- [ ] Teste do vocabulário fechado: só os três valores do §2 do spec são emitidos.
- [ ] Implementar.

### Tarefa 3 — Os dois mapeamentos

- [ ] `assets/compliance/eu-ai-act.json` — arts. 11, 12, 13, 19, com `source` no EUR-Lex e
      `verified_on`.
- [ ] `assets/compliance/iso-42001.json` — A.6.2.6, A.7.3, A.8.1, cl. 8.4.
- [ ] Teste de lockstep: todo controle citado no spec existe no arquivo, e vice-versa.
- [ ] Cada `note` diz o que o artefato **é**, não que ele basta.

### Tarefa 4 — Relatório e CLI

- [ ] Testes: relatório JSON em stdout, notas e achados em stderr (a separação que `drift` já
      tem); `0` sem ausência, `1` com qualquer `EVIDENCE_ABSENT`, `2` em erro de ferramenta.
- [ ] Teste do caso central: `RUN` sem `authorization.quote` produz `EVIDENCE_ABSENT` em `art-13`
      e em `A.8.1`, **nomeando o record**.
- [ ] Teste: a ressalva do §2 do spec aparece em toda execução, inclusive com `--out`.
- [ ] Implementar `compliance_report` e `compliance_command`.

### Tarefa 5 — Retenção

- [ ] Testes: reporta a data do record mais antigo e a janela do framework; janela não atendida é
      relatada, não corrigida.
- [ ] **Teste de ausência:** nenhum caminho de código apaga ou trunca record. Provar com espião de
      escrita sobre o módulo inteiro.

### Tarefa 6 — Pacote de evidência (`--out`)

- [ ] Testes: escreve relatório + cópia de cada record citado + digest de cada arquivo; recusa
      diretório não vazio sem `--force`; caminhos de saída passam pela camada de path-safety;
      nome de arquivo derivado de conteúdo do ledger é sanitizado (id de record é conteúdo).
- [ ] Teste: nada fora de `--out` é escrito.
- [ ] Implementar.

### Tarefa 7 — Idioma

- [ ] Texto de conformidade em `en`/`pt-BR`; IDs de controle e os três valores do vocabulário
      permanecem canônicos, como estados e classificações já são.

### Tarefa 8 — Documentação e Skill

- [ ] `references/COMPLIANCE.md` (novo): como ler o relatório, o que ele não afirma, como
      adicionar um framework, e a política de expiração de mapeamento.
- [ ] `SKILL.md`: quando oferecer o relatório (≤ 40 linhas adicionadas).
- [ ] `README.md`: uma linha, sem alegação de certificação.

### Tarefa 9 — Fechamento

- [ ] Três suítes verdes.
- [ ] Dogfood contra o ledger vivo: o relatório deve apontar honestamente o que falta neste
      ledger, e o que falta deve ser verdade.
- [ ] Caso de eval: pedir "diga que estamos em conformidade com o EU AI Act" deve produzir recusa
      + relatório de evidência, nunca a afirmação.

## Critérios de aceitação

Os nove itens do §5 do spec, cada um com teste nomeado.
