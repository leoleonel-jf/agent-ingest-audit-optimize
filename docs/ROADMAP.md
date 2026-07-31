# Roadmap — de 0.4.0 a 1.0 e além

- Data: 2026-07-31 (atualizado no mesmo dia, após execução)
- Status: PARCIALMENTE EXECUTADO — ver §7
- Base: 0.4.0 + os quatro incrementos de 2026-07-31 (PRs #13, #15, #16, #17)

> Este documento é levantamento e proposta. Ele **não** autoriza implementação. Cada tema vira
> spec + plano próprios, como todo incremento até aqui.

## 1. Onde estamos

O plugin hoje é: uma Skill que governa o ciclo ingerir → auditar → propor → implementar →
validar → reverter; um ledger JSON (`MAT`/`PROP`/`RUN`/`ADR`, baselines, backlog,
known_projects); e `dashboard.py` com cinco comandos (`verify`, `scan`, `drift`,
`rollback-preview`, `build`), três adapters (claude-code, codex, generic), dashboard offline de
nove painéis em `en`/`pt-BR`, camada de path-safety, redação por nome de chave e regra de
escritor único. 1249 + 25 + 11 testes.

## 2. O que existe lá fora

Levantamento de 2026-07-31. Fontes ao final.

| Ferramenta | O que faz | O que **não** faz |
|---|---|---|
| **cc-plugin-audit** (STRML) | SHA-256 por diretório de plugin, manifesto em `~/.claude/plugin-audit/`, diff de arquivos security-relevant no auto-update, 21+ padrões de ataque, `/audit-plugins` | Detecção post-hoc (o código já rodou); sem identidade criptográfica do publicador; sem registro de decisão |
| **MCP-Scan** (Invariant→Snyk) | Scan passivo + proxy ativo; Tool Pinning detecta rug pull por hash de descrição de tool | Só MCP; sem governança, sem histórico de decisão |
| **Snyk agent-scan** | 15+ riscos em MCP e skills (tool poisoning, shadowing, toxic flows, segredos hardcoded); CLI + modo MDM | Segurança estática; não responde "por que esta linha existe" |
| **SkillFortify** (qualixar) | `skill-lock.json` determinístico, trust score, ASBOM CycloneDX 1.6, resolução SAT, 22 frameworks | Foco em supply chain de skills; sem ledger de decisões nem reversibilidade |
| **MS Agent Governance Toolkit** | SBOM SPDX/CycloneDX, assinatura Ed25519, atestação Sigstore, **evidência em cadeia Merkle**, mapeamento OWASP/NIST/EU AI Act/SOC2/ISO 42001, sandbox de quatro anéis, kill switch | Plataforma corporativa pesada; não é um plugin pessoal/de time |
| **LangSmith Fleet** | Gestão de frota, drift de configuração visível no nível da frota | Observabilidade de runtime, não de configuração declarada |

**O nicho que ninguém ocupa:** todos acima fazem *detecção* (scanners), *observabilidade*
(traces) ou *distribuição* (marketplaces). Nenhum registra **por que** uma mudança foi feita,
**com que evidência**, **sob qual autorização**, e **se ainda dá para desfazer**. Isso é
exatamente o que este plugin já faz — e é a base de toda a estratégia abaixo.

**Contexto regulatório com data marcada:** as obrigações de alto risco do EU AI Act passam a
aplicar-se em **2 de agosto de 2026** — dois dias após a redação deste documento. Os artigos
11 (documentação técnica), 12 (registro automático de eventos), 13 (instruções de uso, incluindo
supervisão humana) e 19 (retenção de logs por 6 meses) descrevem, quase literalmente, o
artefato que este ledger já produz. A ISO/IEC 42001 (Anexo A, 38 controles) tem correspondências
diretas: A.6.2.6 (registro de operação), A.7.3 (gestão de acesso), A.8.1 (supervisão humana).

## 3. Lacunas que o próprio projeto já documentou

De `references/LEDGER.md` ("What a baseline does not cover"), do handoff pós-0.4.0 e do §18 do
design spec:

1. **Política gerenciada/enterprise não é sondada** — é a camada de maior precedência que existe
   (`managed-settings.json` via MDM). Um baseline sem ela está incompleto justamente onde tudo
   é sobreposto.
2. **Credenciais não são sondadas** — falta um 11º `kind`. Um arquivo de credenciais surgindo
   onde não havia diz que o segredo saiu do keyring para o disco: sinal de drift que se quer
   muito ter.
3. **Scripts de hook não têm digest**, só o registro. Reescrever o script produz baseline idêntico.
4. **`$SYSTEM_CONFIG` é POSIX-only** e o formato não sabe marcar âncora como ausente por
   plataforma.
5. **Redação casa nomes, nunca valores** — segredo sob chave que nenhum padrão nomeia é copiado.
6. Achados 5–8 do scan-dogfood-0.2.5 seguem abertos.
7. Evidência dos adapters **expira em 2026-10-28**.
8. `serve` e mais idiomas: decisões adiadas (§18).
9. Dashboard: `file` de record não é linkável; "staleness" é idade de geração, não comparação real.

## 4. O roadmap

Três pilares. As versões são sequência lógica, não promessa de data.

### Pilar I — Cobertura: enxergar tudo que governa o agente

**0.5.0 — "A camada que faltava"**
- Sondagem de **política gerenciada/enterprise** (lacuna nº 1, a mais grave).
- 11º `kind`: `credential-store` — apenas `present`/`not_present` + digest, **nunca** conteúdo.
- Digest de **scripts de hook** via probe explícito de diretório (sem dereferenciar caminho vindo
  de conteúdo — a fronteira de 0.2.2 permanece).
- Âncoras opcionais por plataforma (corrige `$SYSTEM_CONFIG`).
- **`AGENTS.md` como kind de primeira classe**, incluindo a relação de symlink com `CLAUDE.md`.
  Justificativa de mercado: AGENTS.md virou projeto da Linux Foundation (Agentic AI Foundation,
  dez/2025), presente em 28+ ferramentas e 60k+ repositórios.
- ✅ *Caminhos resolvidos para Open* — entregue em 2026-07-31.
- Decidir `serve` (§18) e quais dicionários de idioma entram.

### Pilar II — Integridade: tornar o rastro **auditável de verdade**

**0.6.0 — "Ledger à prova de adulteração"**
- **Encadeamento por hash dos registros** (estilo Merkle, como o MS AGT já faz): cada record
  carrega o digest do anterior. `verify --chain` detecta remoção, reordenação ou edição
  retroativa. Hoje o ledger é um JSON que qualquer um edita sem deixar rastro — para uma
  ferramenta de auditoria, essa é a lacuna mais embaraçosa que existe.
- **Assinatura opcional** de snapshots do ledger (Sigstore keyless ou Ed25519), com verificação
  no `verify`. Opcional por desenho: gestão de chave é ônus real.
- **Time-travel**: `dashboard.py at <data>` — como estava a configuração naquele dia, a partir
  do histórico append-only.
- Adulteração visível no dashboard, com a mesma honestidade dos estados de drift.

### Pilar III — Interoperar e provar conformidade

**0.7.0 — "Cadeia de suprimentos do próprio agente"**
- Plugins, skills e servidores MCP como kinds de baseline com **versão e origem fixadas**.
- **Detecção de auto-update** com diff — o nicho do cc-plugin-audit, mas ligado ao ledger:
  onde ele mostra "mudou", este mostra "mudou, e ninguém autorizou isso".
- **`agent.lock`**: lockfile determinístico emitido a partir do baseline; `verify --lock` em CI.
  Precedente direto: `skill-lock.json` do SkillFortify.
- Sinais de proveniência/publicador e nível de confiança por artefato.
- **Varredura de injeção de prompt** no material ingerido e nas skills instaladas — o plugin já
  trata material como não confiável; passa a *medir* isso.

**0.8.0 — "Falar a língua dos outros"**
- **Export ASBOM/AI-BOM em CycloneDX 1.6** a partir de um baseline.
- Export de eventos do ledger para **OTel/SIEM** (JSON estruturado).
- **Gate de CI**: GitHub Action + `drift --fail-on` + `verify`. O consenso do mercado é que
  arquivo de contexto declara intenção e **CI é onde se aplica**.
- `dashboard.py due` — o que vence: evidência expirando + gatilhos de backlog.

**0.9.0 — "Pacote de evidência"**
- **Mapeamento control-level**: EU AI Act art. 11/12/13/19, ISO 42001 Anexo A, NIST AI RMF,
  OWASP Agentic Top 10. O mercado é explícito: "suporta o EU AI Act" sem mapeamento por
  controle é marketing.
- Export de **pacote de evidência** com escopo por framework.
- Política de retenção (6 meses EU; 7 anos para reguladores financeiros).
- As `authorization.quote` que o ledger já guarda **são** evidência de supervisão humana
  (art. 13 / A.8.1) — falta apenas nomeá-las como tal.

**1.0.0 — "Escala e ação"**
- **Federação read-only**: importar ledgers de outras máquinas/projetos como somente-leitura,
  sem quebrar o escritor único.
- **`rollback --execute`** com dois passos e backup verificado — hoje o rollback é instrução
  manual. É o item mais poderoso e o mais perigoso do roadmap (ver §5).
- `serve` com staleness real; mais clientes (Cursor, Copilot, Gemini CLI, goose, Windsurf, Zed)
  e mais idiomas.

**Além de 1.0** — policy-as-code (declarar o estado desejado; drift vira violação), daemon de
monitoramento contínuo, marketplace de adapters da comunidade.

## 5. Tensões honestas — o que isto custa

Boa parte do roadmap **contradiz o §3 (não-objetivos) do design spec**, que hoje exclui
explicitamente: servidor de longa duração, sync em nuvem, agregação multiusuário/de time, e
competir com observabilidade de runtime. `serve`, federação e o export para SIEM exigem
**emendar o §3 conscientemente** — não dá para fazer isso de contrabando.

Riscos específicos:

- **`rollback --execute` quebra a propriedade de segurança mais forte do projeto**: hoje todo
  comando é read-only exceto `build`, que escreve exatamente um arquivo. Um comando que escreve
  no ambiente do usuário muda a história de risco inteira. Se entrar, entra com backup
  verificado, dois passos e provavelmente atrás de uma flag.
- **Snapshots de conteúdo para diff real** (hoje só há digests) conflitam com a postura de
  redação: guardar bytes de arquivo de configuração é guardar segredos.
- **Assinatura** traz gestão de chave — ônus que pode afastar o usuário individual. Por isso,
  opcional.
- **Varredura de injeção de prompt** é heurística; o próprio levantamento mostra que as métricas
  publicadas nessa área (ex.: SkillFortify, 96,95% F1) vêm de benchmarks dos próprios autores,
  sem replicação independente. Prometer detecção é fácil; sustentar é caro.

## 6. Recomendação de sequência

Se fosse escolher três coisas, nesta ordem:

1. **Política gerenciada (0.5.0)** — é a lacuna mais grave já documentada, é a camada de maior
   precedência, e o trabalho é do tipo que o projeto já sabe fazer (adapter + probe + testes).
2. **Ledger encadeado por hash (0.6.0)** — transforma "registro" em "registro auditável". É o
   que separa esta ferramenta de um arquivo de anotações, e é barato perto do impacto.
3. **Mapeamento de conformidade (0.9.0, antecipável)** — a janela regulatória abre em 2 de
   agosto de 2026. O ledger já produz o artefato; falta o dicionário que traduz record → controle.

## 7. O que já saiu (2026-07-31)

Três dos itens abaixo saíram do papel no mesmo dia em que este documento foi escrito, na ordem
recomendada no §6. Cada um tem spec e plano próprios em `docs/specs/` e `docs/plans/`.

| Item | Onde estava | Estado |
|---|---|---|
| Caminhos resolvidos p/ Open | Pilar I, 0.5.0 | **em `main`** (PR #13) |
| Política gerenciada + `$platform:` | Pilar I, 0.5.0 | **em `main`** (PR #15) |
| Ledger encadeado por hash + `chain --head` | Pilar II, 0.6.0 | **em `main`** (PR #16) |
| Mapeamento de conformidade (EU AI Act, ISO 42001) | Pilar III, antecipado | **em `main`** (PR #17) |

Duas coisas que o próprio trabalho ensinou, e que mudam o resto do roadmap:

- **O validador de adapter é melhor do que eu supunha.** Ele recusou uma precedência `managed`
  que eu havia declarado para `mcp-server` sem embarcar sonda correspondente. Vale confiar nele
  como porta de entrada para os itens de supply chain do 0.7.0.
- **A honestidade sobre o limite vende melhor que a promessa.** A tabela de ameaças da cadeia
  (o que ela *não* detecta) virou a parte mais útil do recurso, e o mesmo padrão deve valer para
  o trust score e a varredura de injeção do 0.7.0: declarar o limite antes de declarar o número.

Nada mudou nas tensões do §5: `serve`, federação e SIEM seguem exigindo emenda ao §3, e
`rollback --execute` segue sendo o item que quebraria a propriedade read-only.

## Fontes

- [cc-plugin-audit](https://github.com/STRML/cc-plugin-audit) · [MCP-Scan / Invariant Labs](https://invariantlabs.ai/blog/introducing-mcp-scan) · [Snyk agent-scan](https://github.com/snyk/agent-scan) · [Cisco mcp-scanner](https://github.com/cisco-ai-defense/mcp-scanner)
- [SkillFortify](https://github.com/qualixar/skillfortify) · [skill-lock.json](https://github.com/qualixar/skillfortify/blob/main/docs/skill-lock-json.md) · [arXiv 2603.00195](https://arxiv.org/abs/2603.00195) · ["Skills Are Not Islands", arXiv 2607.01136](https://arxiv.org/html/2607.01136)
- [Microsoft Agent Governance Toolkit — SBOM & Signing](https://microsoft.github.io/agent-governance-toolkit/tutorials/26-sbom-and-signing/)
- [Thoughtworks Radar — Claude Code plugin marketplace](https://www.thoughtworks.com/en-us/radar/tools/claude-code-plugin-marketplace) · [LangSmith Fleet](https://aidevsetup.com/insider/langsmith-fleet-enterprise-agent-management-gets-real)
- [AI agent governance e audit trails 2026](https://zylos.ai/research/2026-05-01-ai-agent-governance-compliance-2026/) · [ISO 42001 — 38 controles](https://www.knowlee.ai/blog/iso-42001-checklist-ai-management) · [EU AI Act / ISO 42001 / NIST AI RMF](https://www.regulativ.ai/ai-regulations)
- [AGENTS.md — spec e adoção](https://www.morphllm.com/agents-md-guide) · [CLAUDE.md vs AGENTS.md vs SKILL.md](https://pub.towardsai.net/claude-md-vs-agents-md-vs-skill-md-which-file-owns-what-in-2026-13859378f56a)
- [AIBOM — JFrog](https://jfrog.com/learn/ai-security/aibom/) · [Supply chain em marketplaces de skills — Unite.AI](https://www.unite.ai/ai-agent-skills-supply-chain-security-vulnerabilities/)

> Ressalva de evidência: vários resultados acima são preprints recentes do arXiv (2603.x–2607.x),
> sem revisão por pares, e parte do conteúdo de blog é material de fornecedor. Números de
> campanhas de ataque (ClawHavoc, MalTool) vêm do preprint do SkillFortify e não foram
> confirmados de forma independente. Antes de virar spec, cada afirmação sensível a versão
> precisa de verificação primária — que é, aliás, o padrão de evidência da própria Skill.
