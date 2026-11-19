# Parecer: revisão do plugin (fase 1, diagnóstico)

- Data: 2026-11-18
- Base: `main` em `5377df5` (v0.6.0), lida pela branch `claude/angry-shaw-d1f609`
- Pedido: `docs/prompts/2026-11-18-revisao-do-plugin.md`
- Autor: Odin (Claude Code). Só leitura: nenhum arquivo do plugin foi alterado, nenhum ledger real
  foi tocado.
- Status: parecer fechado, avaliado pela Eve e decidido pelo Leo em 2026-11-18 (ver "Decisões" no
  fim).

## Resumo

O plugin dispara bem e, quando roda, entrega valor real. O problema está em volta: o aparato de
governança cresceu muito além do uso (cerca de 12.000 linhas de código e HTML para ledgers com 0 e
7 registros), parte dele está errada ou vencida, e nada automatizado impede isso de acontecer de
novo. A recomendação é enxugar em torno do caminho principal (auditar material, propor, aplicar o
autorizado), corrigir o que venceu de forma honesta, pôr um CI mínimo e só então renomear.

## Como foi medido

- Três suítes rodadas em árvore limpa: dashboard 1434 testes com 1 falha, packaging 25 com 2
  falhas, evals 11 verdes. Mesma causa nas três falhas.
- Sete frentes de leitura e pesquisa em subagentes (formatos Claude Code, formatos Codex e Agent
  Skills, caminhos dos adapters, conformidade, concorrentes e nomes, inventário de código, execução
  real da Skill). Pesquisa na web em modo padrão, sem ferramenta cobrada por uso.
- Ativação medida em 25 sessões headless limpas (`claude -p`, Claude Code 2.1.326, modelo Opus
  5.5, ferramentas de escrita removidas), com os 10 casos de ativação de `evals/suite.json` e 8
  pedidos reais em português.
- Caminho principal exercitado uma vez de ponta a ponta com material real (artigo de boas práticas
  do Claude Code), até a proposta, sem escrever no ledger.
- Reconferência própria dos achados de maior impacto: `agent-plugins.org/specification`,
  `developers.openai.com/plugins/build/plugins` e `code.claude.com/docs/en/plugins/components`
  abriram e confirmam. O EUR-Lex devolveu página vazia na reconferência (ver achado 1).

Limites da medição: a ativação foi medida no ambiente do Leo, onde o plugin `superpowers` empurra
o modelo a invocar Skills, o que tende a inflar a taxa. O caminho principal foi rodado uma vez só,
num único material. As páginas da OpenAI chegaram em parte como resumo de modelo, não texto bruto.

## Achados, em ordem de impacto

### 1. O mapeamento de conformidade está errado desde a origem

Evidência:

- `assets/compliance/eu-ai-act.json:26-27` chama o Art. 13 de supervisão humana. O Art. 13 é
  transparência e informação aos deployers; supervisão humana é o Art. 14. O erro se repete em
  `references/COMPLIANCE.md:62,74`, `ledgerlib/compliance.py:6`, `iso-42001.json:36`,
  `CHANGELOG.md:156` e nos testes (`dashboard/tests/test_compliance.py:342,388`).
- `assets/compliance/iso-42001.json`: `A.6.2.6` não é registro de logs (é operação e
  monitoramento; logs é `A.6.2.8`); `A.7.3` não é gestão de acesso (é aquisição de dados, e o
  Anexo A não tem controle de gestão de acesso); `A.8.1` não existe (o grupo A.8 vai de A.8.2 a
  A.8.5; supervisão humana aparece em A.9.2). A cláusula 8.2 é avaliação de risco, não o vínculo
  risco-controle (6.1.3 e 8.3). Fonte só secundária para os títulos da ISO: a norma é paga.
- A data "2 de agosto de 2026" (`compliance.py:3`, `CHANGELOG.md:153`, `docs/ROADMAP.md`) mudou:
  o subagente leu no EUR-Lex o Regulamento (UE) 2026/1744 (Digital Omnibus), que leva as
  obrigações de alto risco do Anexo III para 2/12/2027 e do Anexo I para 2/8/2028. Minha
  reconferência do mesmo endereço devolveu página vazia; reabrir antes de editar qualquer coisa.
- `retention_days: 180` fica abaixo de seis meses.
- O mapeamento vence em 31/01/2027 e, vencido, o comando recusa rodar (`compliance.py:113-122`).

Por que pesa: é um plugin cujo propósito é auditar afirmações contra fonte primária, e ele
publica quatro identificadores de controle errados, cobertos por testes que confirmam o erro.

Ação proposta: retirar o comando `compliance` do plugin (417 linhas, 2 JSON, 42 testes, nenhum
módulo depende dele, uso real zero), com registro no CHANGELOG. Alternativa: corrigir contra uma
cópia licenciada da norma e o texto consolidado do regulamento.

### 2. A `main` está vermelha, e renovar a data dos adapters seria falso

Evidência:

- Os três adapters declaram `"expires_on": "2026-10-28"`. O `scan` trata vencimento como achado e
  sai com código 1 (`ledgerlib/scan.py:967-978`); três testes rodam o `scan` sem injetar data e
  por isso falham pelo calendário.
- Reverificação contra a documentação de hoje: só o `generic` pode ser renovado como está.
- `claude-code.json` precisa de edição: o Claude Code lê `AGENTS.md` e `.claude/AGENTS.md` desde a
  2.1.277 quando não há `CLAUDE.md` (inverte o achado 1 da pesquisa de julho);
  `settings.local.json` no nível do usuário não é documentado (é só de projeto); `~/.claude.json`
  acompanha `CLAUDE_CONFIG_DIR`, e servidores de escopo local ficam em
  `/projects/<caminho>/mcpServers`; faltam `managed-mcp.json`, política por registro do Windows,
  `.claude/agents/` e `.claude/commands/` de projeto, `output-styles/`, plugins sincronizados.
- `codex.json` precisa de edição: não sonda `hooks.json`, `rules/*.rules`, `agents/*.toml`,
  `requirements.toml`, plugins nem MCP; a regra de resolução de skill mudou (homônimas não se
  sobrepõem mais); `~/.codex/skills` virou caminho depreciado; não há âncora de sistema no Windows.
- Nesta máquina existem `~/.codex/hooks.json`, `~/.codex/rules/` e `~/.claude/output-styles/`, que
  nenhum adapter enxerga.

Sobre o desenho da validade: avisar o usuário está certo; depender do relógio para a suíte passar
está errado. Proposta: os testes injetam a data; um teste separado, rodado em CI agendado, falha
quando faltarem 14 dias para o vencimento de qualquer evidência embarcada; para quem tem versão
antiga instalada, o aviso continua, mas o vencimento deixa de fazer `update` terminar como falha.

Lacunas: `claude mcp list --json` não é documentado; os caminhos de sistema do Codex no Windows só
aparecem no código-fonte da `main` deles, não na documentação.

### 3. Os formatos de plugin mudaram por baixo do plugin

Evidência:

- Codex: o manifesto padrão passou a ser `plugin.json` na raiz do plugin (especificação Agent
  Plugins 1.0.0), com os campos da OpenAI em `extensions["com.openai"]`.
  `.codex-plugin/plugin.json` segue lido como compatibilidade. O repositório só tem o formato
  antigo.
- Diretório da OpenAI: `shortDescription` aceita até 30 caracteres; o do plugin tem 49
  (`.codex-plugin/plugin.json`). `displayName` tem exatamente 30.
- `README.md:68` manda rodar `codex plugin add`, que a documentação atual não lista.
- A validação em runtime no Codex (`docs/validation/codex-runtime-validation-0.1.1.md`) é da
  0.1.1, de 28/07, anterior à mudança de formato.
- Claude Code: `commands/` é formato legado, e a documentação diz que skills o substituem para
  trabalho novo. `commands/dashboard.md:31` usa caminho relativo
  (`python skills/.../dashboard.py`), que só resolve com o diretório de trabalho no próprio
  repositório; a documentação oferece `${CLAUDE_PLUGIN_ROOT}`. O teste da 0.6.0 foi feito dentro do
  repositório, então o defeito não apareceria. Não foi testado fora dele nesta revisão.
- `claude plugin validate .` passa sem achados. A especificação Agent Skills não teve mudança
  normativa desde julho, e o frontmatter está conforme.

Ação proposta: `plugin.json` na raiz conforme a especificação, mantendo o antigo como
compatibilidade; `/dashboard` vira skill com `${CLAUDE_PLUGIN_ROOT}`; corrigir `shortDescription`
e o README; revalidar no Codex atual.

Lacuna: efeito de um `plugin.json` na raiz sobre o Claude Code, que hoje lê
`.claude-plugin/plugin.json`. Checagem: `claude plugin validate` numa cópia com os dois.

### 4. A Skill dispara bem; o custo está depois do disparo

Ativação (25 sessões limpas): 23 corretas. Negativos 8 de 8. Positivos 15 de 17; as duas falhas
foram pedidos de "revisar antes de instalar" (servidor MCP e skill), que dispararam em 8 de 10
tentativas. A descrição de 760 caracteres cabe nos limites do Claude Code (1.536) e da
especificação (1.024); no Codex a lista de skills encurta descrições longas primeiro, então os
gatilhos devem vir no começo.

Caminho principal, uma execução real:

- Cerca de 7 minutos, resposta de 1.543 palavras, uma decisão com três propostas.
- Consumo: cerca de 190 mil tokens no agente principal e 295 mil em três subagentes de
  verificação.
- O que a Skill acrescentou de verdade: a comparação com o ambiente real (achou o modo de
  permissão padrão divergente do que o `CLAUDE.md` descreve e a falta de regras `deny` para
  segredos), a verificação por afirmação, a separação entre obtido e não obtido, e teste, critério
  e rollback por proposta.

Atritos medidos:

- Leitura forçada: piso de 1.423 linhas (SKILL 263, WORKFLOW 165, LEDGER 995). Do `LEDGER.md`, o
  executor precisou de umas 80.
- Bookkeeping obrigatório por auditoria: ler o ledger global, capturar baseline, gravar 1 `MAT`,
  3 `PROP` e cerca de 5 entradas de backlog, mais `verify` e `chain --seal`. Tudo isso para ledgers
  que hoje têm 0 e 7 registros.
- Identificadores dependem do ledger global, e o `scan` exige `--id` até para leitura.
- Os resumos "Initial Technical Summary" e "Final Technical Summary" são obrigatórios, repetem
  conteúdo e brigam com a regra do leitor de resultado primeiro.
- Rótulos em inglês em caixa alta e a frase `Implement proposal PROP-…` como única forma de
  autorizar: não combina com um leitor que responde por botão em português.
- Treze classificações: `TEST IN ISOLATION` não pode virar proposta, e o executor teve de
  reclassificar para conseguir propor. O teto de três propostas adiou uma correção de duas linhas.
- A seção de modelo e esforço não serviu para nada no caminho comum.
- "Delegue para preservar contexto" é conselho que a documentação atual da Anthropic lista como
  ultrapassado.
- Tom: 25 ocorrências de "never" no `SKILL.md` e 45 no `LEDGER.md`.
- O `scan` leu e imprimiu 29,5 KB com valores de `settings.local.json` e `~/.claude.json`.

Ação proposta: reescrever a Skill em torno do caminho principal. Resultado primeiro, uma decisão
por vez, classificações reduzidas (cinco bastam), registro leve por padrão (um registro por
auditoria) e o aparato completo só quando houver implementação autorizada. `LEDGER.md` dividido
por assunto, com índice.

### 5. Não há CI, e o processo só existe nesta máquina

Evidência: não existe `.github/`. A 0.6.0 entrou direto na `main`. `.agent-audit/` é ignorada pelo
git, então os cinco handoffs e o ledger de dogfood vivem só no checkout principal. O `CLAUDE.md`
do projeto tem uma linha e não é versionado. Já houve um defeito só de POSIX (v0.2.4) que a suíte
rodada só no Windows não via.

Ação proposta, o menor CI que resolve: um workflow em push e PR, em Ubuntu e Windows, com as três
suítes e a validação de `evals/suite.json` (a consistência de versão já é teste de packaging); um
segundo, agendado, com o teste de vencimento do achado 2. Versionar: um `CLAUDE.md` de projeto de
verdade e os handoffs em `docs/handoffs/`.

Lacuna: `claude plugin validate` no runner exige instalar o CLI; falta conferir se roda sem
autenticação.

### 6. O aparato cresceu além do uso

Inventário: 6.941 linhas de Python, 5.067 de HTML, 1.434 testes. Uso real: 0 registros no ledger
global do Claude Code, 7 no do Codex, dogfood no do projeto.

| Parte | Linhas | Quem depende | Destino proposto |
|---|---|---|---|
| `compliance` | 417 + 2 JSON | ninguém | sai (achado 1) |
| `lock` | 265 | ninguém | sai do caminho da Skill; fica como comando avulso ou sai |
| `chain` | 360 | `verify`, `build`, `lock`, `update` | fica, mas `--seal` deixa de ser rotina obrigatória |
| `update` | 317 | só o `/dashboard` | fica opcional |
| `build` + dashboard | 596 + 5.067 | `update` | fica opcional; 5 dos 9 painéis mostram algo que o CLI não mostra |
| `scan` + adapters | 1.973 | `drift`, `rollback`, `update`, `lock` | fica, fora do caminho padrão de análise |
| `drift`, `rollback-preview` | 697 + 337 | `build` | ficam, só quando há implementação |
| `verify` + `validate` | 729 | quase tudo | fica |

Roadmap: abandonar por escrito assinatura, `at <data>`, CycloneDX, export para SIEM, federação,
`rollback --execute`, `serve`, NIST e OWASP, policy-as-code e daemon. Manter como candidatos:
digest de script de hook, `AGENTS.md` como tipo de primeira classe, mais clientes. Mais idiomas
só sob pedido.

### 7. O nicho segue vago, a vizinhança lotou

- Ninguém registra por quê, com que evidência, sob qual autorização e se dá para desfazer uma
  mudança de configuração de agente. O mais próximo em palavras é um repositório sem estrelas,
  voltado a runtime.
- Em volta, scanners, lockfiles e inventários ficaram grandes: Snyk agent-scan (3,3 mil
  estrelas), Cisco skill-scanner (2,7 mil), Microsoft Agent Governance Toolkit (6,6 mil),
  microsoft/apm (4,4 mil), agentshield (1,4 mil).
- Os clientes ganharam recursos nativos: `claude plugin eval`, `/skill-doctor`, varredura
  automática na submissão ao catálogo comunitário, pin por SHA. Não há nativo para registro de
  decisão, drift nem lockfile de configuração.

Leitura: não vale competir em scanner, lockfile ou BOM. O diferencial é a auditoria de material
com decisão registrada, que é também o que de fato funciona hoje.

### 8. Avaliação: manter a suíte e acrescentar uma camada nativa pequena

`claude plugin eval` lê `evals/<caso>/prompt.md` com `graders/*.md`, não lê `suite.json`, e não
calcula precisão, recall nem a campanha de modelo e esforço. Cada execução é chamada real de
modelo. Proposta: `suite.json` continua como conjunto de referência; acrescentar uma camada nativa
só de ativação, com poucos casos positivos e negativos, rodada à mão antes de release e não a cada
push. `/skill-doctor` não tem página pública de documentação: lacuna.

### 9. Segurança

As três lacunas seguem abertas: redação por nome de chave (`ledgerlib/scan.py:130-150`), script
de hook sem digest (os probes leem só `/hooks` do settings) e credenciais não sondadas
(`ledgerlib/constants.py:148-159`). Reavaliação: a redação sobe de prioridade, porque o `scan`
copia valores de dois arquivos de configuração do usuário para a saída; digest de hook fica média;
credenciais fica baixa. Se o `scan` sair do caminho padrão, as três caem um degrau.

## Nome

| Candidato | Colisão | Leitura |
|---|---|---|
| `plugin-reviewer` | livre em npm, PyPI e nos catálogos; um repositório homônimo de auditoria de plugin WordPress (9 estrelas) | livre, genérico; sugere revisão de código de plugin |
| `agent-auditor` | npm e PyPI tomados, cerca de 25 repositórios homônimos pequenos, 5 skills em skills.sh; ausente dos catálogos da Anthropic e da OpenAI | disputado fora dos catálogos que importam |
| `agent-ledger` | PyPI tomado, repositórios homônimos com 106 e 81 estrelas, `codeledger` no catálogo comunitário | disputado, e vende a parte menos usada |
| `agent-config-ledger`, `agent-decision-ledger` | livres em tudo que foi checado | livres, mas também vendem o ledger |

Nenhum candidato aparece como nome de plugin em `claude-plugins-official` (317 plugins) nem em
`claude-plugins-community` (2.283), nem nos repositórios de plugins e skills da OpenAI.

Sobre a submissão de julho: o plugin não aparece em nenhum dos dois catálogos da Anthropic, então
não há sinal público de aceite. O status no Console exige login. A documentação diz para nunca
mudar o nome de um plugin publicado e oferece o mapa `renames` em marketplace próprio; a regra de
renomeação no diretório da Anthropic não foi encontrada.

## Recomendação de corte

Entra agora, nesta ordem, um incremento por PR:

1. `main` verde de forma honesta: adapters reverificados e editados, testes sem relógio.
2. CI mínimo e versionamento do processo.
3. Corte: `compliance` fora, roadmap abandonado por escrito, `lock` e `chain --seal` fora do
   caminho padrão. Antes do rename, para renomear menos.
4. Formatos: `plugin.json` na raiz, `/dashboard` como skill, textos do Codex.
5. Skill enxuta: saída, registro leve, classificações, `LEDGER.md` dividido.
6. Rename isolado, com migração dos diretórios de dados, e release própria.

Fica para depois: redação por valor, digest de hook, `AGENTS.md` como tipo, camada nativa de
avaliação, mais clientes.

Sai do plugin: `compliance`, e o que resta dos pilares II e III do roadmap.

## Respostas à seção 3 do prompt

| Pergunta | Onde está respondida |
|---|---|
| Formatos de plugin e Skill | achado 3 |
| Caminhos dos adapters | achado 2 |
| Validade de 90 dias | achado 2 |
| `claude plugin eval` e `/skill-doctor` | achado 8 (lacuna: `/skill-doctor` sem documentação pública) |
| EU AI Act e ISO 42001 | achado 1 (lacuna: norma ISO paga; EUR-Lex a reabrir) |
| Concorrentes e nicho | achado 7 |
| Ativação da Skill | achado 4 |
| Caminho principal real | achado 4 (uma execução, um material) |
| Calibração para modelos atuais | achado 4 |
| Saída e leitor | achado 4 |
| Comandos e painéis, um a um | achado 6 |
| Roadmap | achado 6 |
| CI mínimo | achado 5 (lacuna: `claude plugin validate` sem autenticação no runner) |
| O que versionar | achado 5 |
| Segurança | achado 9 |

## O que não foi verificado

- `/dashboard` fora do repositório: inferência a partir do caminho relativo, sem execução.
- Títulos dos controles da ISO/IEC 42001: só fonte secundária.
- Regulamento (UE) 2026/1744: lido por subagente, reconferência devolveu página vazia.
- Status da submissão de julho no Console e nos diretórios dentro dos apps: exigem login.
- Ativação com outro modelo, sem o `superpowers` e no Codex.
- Validação em runtime no Codex atual.

## Avaliação da Eve (2026-11-18)

A Eve leu o parecer no SHA `6a8c1e2` e gravou a avaliação dela fora do repositório (em
`.agent-audit/`, pasta ignorada pelo git). Ela concorda com a direção. O que muda neste parecer:

- **Segurança sobe para o começo.** Ela reproduziu em memória, com dados fictícios, que valores
  sob chaves não previstas passam pela redação: um comando de hook com `--password` e uma regra de
  permissão com cabeçalho `Authorization` saíram intactos, e `update.py:_append_baseline` grava a
  saída do `scan` no ledger. A correção entra antes do rename, com minimização e digest de campos
  opacos em vez de confiar em regex.
- **Defeito novo: o ZIP do plugin não inclui `commands/dashboard.md`.**
  `packaging/scripts/package_plugin.py` não cita `commands/` (conferido). O teste de pacote deve
  checar os componentes prometidos no arquivo extraído, não a própria lista do empacotador.
- **Correções ao achado 4.** `Implement proposal PROP-…` é exemplo ("such as"), não a única forma
  de autorizar. O teto de três propostas tem exceção a pedido do usuário. `TEST IN ISOLATION` é
  aceito pelo schema; o atrito está na instrução, não no validador.
- **Correção ao achado 7.** "Ninguém registra" é um universal que a busca não demonstra. Leia-se:
  não encontramos equivalente nas fontes consultadas.
- **Achado 1.** Ela abriu o PDF oficial do Regulamento (UE) 2026/1744: o art. 1(40) altera o
  art. 113 com as datas de 02/12/2027 e 02/08/2028 para os grupos de alto risco indicados. Nem
  toda a aplicação do regulamento saiu de 02/08/2026. Os títulos da ISO seguem sem fonte primária.
- **Achado 2.** Nem todo código de saída 1 deve virar sucesso: há quem precise recusar baseline
  desatualizado. Proposta dela: avisos estruturados e um modo estrito para CI.
- **Achado 5.** CI sem checks obrigatórios e política de branch não impede push direto. Handoffs
  só entram no git depois de retirados os dados privados.
- **Achado 3.** `extensions.com.openai`, quando presente, substitui o overlay inteiro, sem merge.

## Decisões do Leo (2026-11-18)

1. **Nome:** `plugin-reviewer`.
2. **Escopo:** o carro-chefe passa a ser revisar plugin, skill e servidor MCP antes de adotar. A
   auditoria de vídeo, artigo, repositório e ideia continua, em segundo plano.
3. **Corte:** o recomendado. Sai o comando `compliance`, com aviso de depreciação e histórico
   preservado. O resto dos pilares II e III do roadmap é abandonado por escrito. `scan`, dashboard,
   `lock` e o selo da cadeia continuam existindo, fora do caminho padrão da Skill. O registro
   passa a ser um por revisão.

Ordem de execução, um incremento por PR, já com os pontos da Eve:

1. Suítes sem depender do relógio.
2. CI mínimo.
3. Redação de valores e ZIP completo.
4. Adapters reverificados.
5. Corte.
6. Formatos de plugin.
7. Skill enxuta, com o novo foco.
8. Rename para `plugin-reviewer`, isolado, com release própria.
