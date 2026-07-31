# `agent.lock` — a supply chain the user can pin (0.7.0, increment 1)

Status: PROPOSTO 2026-07-31 — aguarda deliberação
Target version: 0.7.0
Fecha: a primeira metade do pilar "cadeia de suprimentos do próprio agente" do `docs/ROADMAP.md`

## 1. O problema

Um baseline responde "o que havia neste ambiente naquele dia". Ele não responde a pergunta que o
supply chain exige: **"o que deveria haver aqui?"**

A diferença é a mesma entre um `pip freeze` guardado num arquivo de log e um `requirements.lock`
versionado. O baseline é observação, datada e imutável. O lockfile é **intenção declarada**: um
artefato pequeno, legível, versionado em git, que uma passagem de CI compara contra a realidade e
falha quando divergem. Hoje o plugin tem a primeira metade e nenhuma da segunda.

O contexto de mercado é direto: a campanha ClawHavoc (jan–fev 2026) infiltrou skills maliciosas
num marketplace, e a resposta convergente da literatura — SkillFortify (`skill-lock.json`),
"Skills Are Not Islands" — é a mesma: **pinar, versionar, verificar em CI**. Ver `docs/ROADMAP.md`
para as fontes e a ressalva sobre elas.

## 2. Desenho

### 2.1 O arquivo

`agent.lock` é JSON, ordenado, determinístico, e feito para ser lido por gente num diff:

```json
{
  "lock_version": 1,
  "generated_from": "BASE-2026-000",
  "client": "claude-code",
  "adapter_version": 2,
  "platform": "win32",
  "entries": [
    {
      "kind": "skill",
      "name": "agent-ingest-audit-optimize",
      "anchor": "$USER_CONFIG/skills/agent-ingest-audit-optimize/SKILL.md",
      "scope": "user",
      "digest": "sha256:…",
      "state": "present"
    }
  ]
}
```

Sem timestamp, sem caminho absoluto, sem nada específico da máquina além de `platform` — duas
máquinas com a mesma configuração produzem **bytes idênticos**, ou o arquivo não serve para
diffar. `entries` é ordenado por `(kind, scope, anchor)`. A canonicalização é
`chain.canonical_text`, que já é a única do repositório.

### 2.2 Os comandos

```text
dashboard.py lock <ledger> --from BASE-YYYY-NNN [--out agent.lock]   # escreve
dashboard.py lock <ledger> --check agent.lock                        # read-only
```

`--check` é a passagem de CI. Ele **não** relê o disco: compara o lockfile contra o baseline
nomeado no ledger, que é o que torna a checagem determinística e offline. Verificar contra o
disco de agora já tem comando — é o `drift` — e fundir os dois daria à mesma pergunta duas
respostas.

Saídas de `--check`, vocabulário fechado: `added`, `removed`, `changed` (digest diferente),
`state_changed`. Códigos: `0` idêntico, `1` qualquer divergência, `2` erro de ferramenta.

### 2.3 O que entra

Só os `kind`s que descrevem artefato instalável: `skill`, `plugin`, `mcp-server`, `agent`,
`command`, `hook`. Ficam de fora `instruction-file`, `model-setting`, `permission-rule` e
`env-var-name` — são configuração que muda legitimamente todo dia, e um lockfile que falha o CI
porque alguém editou o `CLAUDE.md` é um lockfile que alguém desliga na primeira semana.

Essa lista é **declarada no adapter**, não fixada em código: `"lockable": true` por probe. Um
adapter novo decide o que faz sentido pinar no seu cliente.

### 2.4 O que este incremento **não** faz

- **Não grava versão nem origem por artefato.** O baseline hoje digere `installed_plugins.json`
  como um blob; extrair versão e marketplace por plugin é o incremento 2 do 0.7.0, e prometer
  isso aqui seria descrever um campo que não existe.
- **Não pontua confiança.** Trust score exige sinais que este plugin não coleta; o roadmap já
  registra que os números publicados nessa área vêm de benchmarks dos próprios autores.
- **Não detecta auto-update sozinho.** Isso é comparar dois baselines, e é o incremento 3.
- **Não assina nada.**

## 3. Aceitação

1. Dois `lock --from` sobre o mesmo baseline produzem **bytes idênticos**.
2. A ordem de `entries` independe da ordem dos itens no baseline.
3. Só `kind`s marcados `lockable` no adapter entram; o resto é ignorado silenciosamente.
4. `--check` idêntico → `0`; artefato adicionado, removido, com digest diferente ou com `state`
   diferente → `1`, cada um nomeado com seu vocabulário.
5. `--check` **não abre nenhum arquivo do ambiente** — provável por espião sobre a camada de path.
6. Baseline inexistente, lockfile ilegível ou `lock_version` desconhecida → `2`.
7. `--out` recusa sobrescrever arquivo que não é um `agent.lock` sem `--force`, como `build` já faz.
8. Lockfile de outro cliente ou outra `platform` é achado explícito, nunca comparação silenciosa.
