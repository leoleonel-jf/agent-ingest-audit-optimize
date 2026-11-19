# Prompt: revisão e modernização do plugin

- Escrito em: 2026-11-18, contra `main` em `5377df5` (v0.6.0)
- Uso: colar numa sessão nova aberta em `D:\dev\leo\agent-ingest-audit-optimize`, ou mandar a
  sessão ler este arquivo e executar
- Os fatos da seção 2 foram medidos nessa data. Confira de novo antes de se apoiar neles.

---

## 1. A missão

Você vai revisar o plugin `agent-ingest-audit-optimize` de ponta a ponta e depois melhorá-lo. O
Leo quer três coisas, nas palavras dele: melhorar o plugin, deixá-lo mais atualizado e deixá-lo
mais eficaz. Ele também quer trocar o nome (seção 5) e te deu liberdade total para propor
mudanças, inclusive cortar o que não se paga.

O plugin está parado desde 04/08/2026. Nesse intervalo os clientes que ele sonda mudaram, o
formato de plugin e de Skill evoluiu, e parte do que ele afirma tem data de validade que já
passou. A revisão existe para descobrir, com evidência, o que envelheceu, o que nunca funcionou
tão bem quanto o texto diz e o que cresceu além do uso real.

"Eficaz" aqui tem um significado preciso: quando o Leo entrega um vídeo, artigo, repositório ou
ideia sobre o ecossistema de agentes dele, o plugin precisa disparar sozinho, auditar as
afirmações contra fonte primária atual, devolver propostas que ele consegue decidir rápido, e
aplicar só o que foi autorizado, com volta. Tudo o mais no repositório (ledger, cadeia de hash,
lockfile, conformidade, dashboard) é apoio a esse caminho. Julgue cada parte por quanto ela
ajuda esse caminho, não por quão bem construída ela é.

## 2. Onde você está

O que o plugin é hoje: uma Skill (`skills/agent-ingest-audit-optimize/SKILL.md`, 263 linhas, com
sete referências e sete templates em Markdown), um CLI em Python só com biblioteca padrão
(`dashboard.py` mais `ledgerlib/`, cerca de 6.900 linhas, com os comandos `verify`, `scan`, `drift`,
`rollback-preview`, `build`, `update`, `chain`, `lock` e `compliance`), três adapters de cliente
(claude-code, codex, generic), um dashboard HTML offline de 5.067 linhas, um comando
(`/dashboard`), manifestos para Claude Code e Codex, e uma suíte de avaliação própria com 34
casos em `evals/`.

Leia nesta ordem antes de formar opinião:

1. `.agent-audit/HANDOFF-2026-08-04-after-0.6.0.md` na raiz do checkout principal (a pasta é
   ignorada pelo git, então não existe em worktree novo: leia pelo caminho absoluto). É o estado
   mais recente e traz as decisões já tomadas.
2. `docs/ROADMAP.md`, que tem o levantamento de concorrentes, as lacunas que o próprio projeto
   documentou e as tensões de desenho.
3. `SKILL.md` e as referências, depois `README.md`, `CHANGELOG.md` (as duas últimas versões) e
   `docs/SUBMISSION.md`.

Estado medido em 18/11/2026, numa árvore limpa:

- **A `main` está vermelha pelo calendário.** `python -m unittest discover -s dashboard/tests`
  dá 1434 testes com 1 falha; `packaging/tests` dá 25 com 2 falhas; `evals/tests` passa (11). As
  três falhas têm a mesma causa: os três adapters declaram `"expires_on": "2026-10-28"`, e o
  `scan` passou a sair com código 1 avisando que a evidência venceu. Para o usuário isso
  significa que todo `scan` e todo `update ledger` hoje terminam em achado.
- `claude plugin validate .` (Claude Code 2.1.326) passa sem achados; ele avisa que a varredura
  de segurança e a revisão de política do diretório não são cobertas por esse comando.
- Não existe CI. Não há `.github/`. A release 0.5.0 já tinha absorvido cinco PRs que entraram
  sem CHANGELOG nem bump de versão, e a 0.6.0 entrou direto na `main`, sem PR.
- A versão está fixada em dez lugares: os oito de `packaging/tests/test_version_consistency.py`,
  o documento `docs/releases/vX.Y.Z.md` e a contagem de casos de avaliação escrita em prosa em
  `docs/SUBMISSION.md`.
- O plugin foi submetido ao marketplace comunitário do Claude Code em 28/07/2026, na versão
  0.1.2. O resultado não está registrado no repositório.
- Uso real, segundo o handoff: o ledger global do Claude Code tem zero registros, o do Codex tem
  sete, e o do projeto é dogfood. Considere isso evidência sobre o quanto o aparato é usado.

## 3. O que a revisão precisa responder

Cada resposta vem com a evidência que a sustenta (saída de comando, trecho de documentação com
data, teste). Onde a evidência não pôde ser obtida, diga qual checagem a obteria.

**Atualidade**

- O que mudou, desde julho, no formato de plugin do Claude Code, na especificação aberta de
  Agent Skills e no formato de plugin do Codex? Compare manifestos, `marketplace.json`,
  `commands/`, `agents/openai.yaml` e a estrutura da Skill com a documentação oficial de hoje, e
  rode `claude plugin validate` no repositório. Seu conhecimento sobre esses formatos pode estar
  defasado: trate a documentação atual como a fonte, não a memória.
- Os caminhos que os adapters sondam ainda são os que os clientes leem? Refaça a verificação
  contra a documentação de cada fornecedor (`docs/research/2026-07-30-client-configuration-paths.md`
  é o método anterior) antes de mexer em qualquer `expires_on`. Empurrar a data sem reverificar
  é exatamente a fraude que o campo existe para impedir.
- Uma validade de 90 dias que derruba a suíte e todo `scan` é o desenho certo? Avalie separar
  "o teste depende do relógio" de "o usuário é avisado", e o que acontece com quem instala uma
  versão antiga.
- Hoje existe `claude plugin eval` e o relatório `/skill-doctor`. A suíte de `evals/` deve ser
  portada, ligada a eles ou mantida como está?
- O mapeamento de conformidade cita datas de aplicação do EU AI Act e controles da ISO 42001.
  Reverifique em fonte primária o que continua verdadeiro.
- O levantamento de concorrentes do roadmap é de 31/07. O nicho descrito ali (registrar por
  quê, com que evidência, sob qual autorização, e se dá para desfazer) continua vago?

**Eficácia da Skill**

- A Skill dispara quando deve e fica quieta quando não deve? A descrição tem 760
  caracteres. Meça com os casos de ativação da suíte e com pedidos reais, em sessão limpa.
- Rode o caminho principal de verdade pelo menos uma vez: um material real, do pedido até a
  proposta. Anote onde há atrito, quanto contexto as referências consomem (`LEDGER.md` tem 995
  linhas) e quanto tempo o Leo levaria para decidir a partir do que sai.
- O texto da Skill ainda está calibrado para os modelos atuais? Procure regras em tom de
  proibição absoluta que hoje geram excesso de zelo, instruções que só existem para contornar
  falhas de modelos antigos, e passos que o modelo já faz sozinho.
- A saída respeita o leitor? Os resumos inicial e final, os rótulos e os treze tipos de
  classificação ajudam a decidir ou só ocupam tela?

**Enxugamento**

- Para cada comando do CLI e cada painel do dashboard: quem usa, para quê, e o que se perde se
  sair. O que não tiver resposta é candidato a corte, a virar opcional ou a ficar fora do
  caminho padrão da Skill.
- O que do roadmap ainda vale (assinatura, `at <data>`, proveniência, CycloneDX, SIEM, `due`,
  federação, `rollback --execute`, `serve`, mais clientes e idiomas) e o que deve ser abandonado
  por escrito?

**Confiabilidade e processo**

- Um CI mínimo (as três suítes, a validação da suíte de avaliação, `claude plugin validate`, a
  consistência de versão) teria pego a `main` vermelha e o lapso de release. Proponha o menor
  que resolve.
- A pasta `.agent-audit/` é ignorada pelo git, então handoffs e decisões vivem só nesta máquina,
  e o `CLAUDE.md` do projeto tem uma linha. O que precisa passar a ser versionado?
- Segurança: a redação casa nomes de chave e nunca valores, os scripts de hook não têm digest e
  as credenciais não são sondadas (lacunas 2, 3 e 5 do roadmap). Reavalie a prioridade.

## 4. Como trabalhar

**Fase 1: diagnóstico, só leitura.** Não altere arquivo do projeto nem estado fora dele. Leitura,
pesquisa, execução das suítes, `claude plugin validate` e dry runs estão liberados. As frentes
da seção 3 são independentes e podem ir para subagentes em paralelo, que devolvem achados
estruturados; a síntese e a priorização ficam com você. Não use Workflow nem ferramenta cobrada
por uso sem o Leo pedir. Pesquisa na web no modo padrão.

**Ponto de decisão, um só.** Entregue no chat um parecer curto: os achados em ordem de impacto,
cada um com a evidência e a ação proposta, e a sua recomendação de corte (o que entra agora, o
que fica para depois, o que sai do plugin). Depois pergunte ao Leo, uma pergunta de múltipla
escolha por vez, com a opção recomendada primeiro e o porquê de cada uma: o nome e o escopo
(seção 5), e o corte. Não estacione decisões em arquivo para ele ler depois.

**Fase 2: execução do que ele aprovou.** Um incremento por vez, na disciplina que o repositório
já tem: spec em `docs/specs/`, plano em `docs/plans/`, teste antes do código, CHANGELOG e os dez
pontos de versão. Cada guarda nova passa por ablação: apague o código, veja um teste nomeado
falhar, restaure. Quatro releases já saíram com guardas que nenhum teste sentiria falta. Cada
incremento entra por PR, com as três suítes verdes antes do merge. Sugestão de ordem, que você
pode trocar com motivo: primeiro deixar a `main` verde de forma honesta, depois o CI, depois o
rename isolado, depois eficácia e enxugamento.

Feche com um handoff novo em `.agent-audit/` no padrão dos anteriores, e um relatório no chat
que separe implementado, testado, mergeado e publicado.

## 5. O nome

O Leo propôs `plugin-reviewer` e aceita sugestões. O nome decide o produto, então trate as duas
coisas juntas na pergunta a ele:

- `plugin-reviewer` descreve bem um produto mais estreito: revisar plugins, skills e servidores
  MCP antes de adotar. Se for esse o desejo, a auditoria de material vira a porta de entrada e o
  restante vira apoio, e isso muda a descrição da Skill e o roadmap. Para o plugin como ele é
  hoje, o nome promete menos do que ele faz e sugere revisão de código de plugin.
- `agent-auditor` cobre as duas metades atuais (auditar o material e auditar o ambiente) e
  mantém a palavra que já está em toda a documentação.
- `agent-ledger` aposta no diferencial que o roadmap identificou e vende mal a parte de ingestão.

Antes de perguntar, verifique colisão de cada candidato: repositórios no GitHub, o marketplace
comunitário do Claude Code, o diretório de plugins da OpenAI e nomes de Skill já publicados.
Leve o resultado para a pergunta.

O rename é uma mudança incompatível e merece incremento e release próprios, sem mudança de
comportamento junto. A superfície medida: 330 ocorrências do identificador em 65 arquivos e 29
do nome de exibição em 28 arquivos. Os pontos que não são busca e troca:

- **Diretórios de dados do usuário.** O ledger global vive em
  `<config do cliente>/agent-ingest-audit-optimize/`, e o adapter local em
  `.../adapters/local.json`. Renomear sem migração deixa ledgers órfãos. Decida entre continuar
  lendo o caminho antigo, migrar com backup ou as duas coisas, e teste em cópia.
- **Identificadores de instalação.** O nome do marketplace, `plugin@marketplace`, o diretório
  da Skill, o `$agent-ingest-audit-optimize` do `openai.yaml` e os nomes dos dois zips mudam
  juntos. Quem tem a versão antiga instalada precisa de um caminho de troca escrito.
- **Histórico.** `docs/releases/`, specs e planos antigos e as entradas passadas do CHANGELOG
  registram o que era verdade, inclusive nomes de arquivo e checksums. Não reescreva.
- **Submissão.** A entrada no marketplace foi feita com o nome antigo e com a identidade do Leo.

## 6. Limites

- Peça o sim do Leo, nomeando a ação, antes de: renomear o repositório no GitHub, publicar tag
  ou release, reenviar ou alterar a submissão em qualquer marketplace, e tocar nos ledgers reais
  (`~/.claude/agent-ingest-audit-optimize/`, `~/.codex/agent-ingest-audit-optimize/`) ou nas
  cópias instaladas do plugin. Commit, push, PR e merge do que você está entregando seguem a
  autonomia de git que ele já deu.
- Não renomeie a pasta local `D:\dev\leo\agent-ingest-audit-optimize`: a memória do projeto e
  as sessões são indexadas por esse caminho.
- Os dois ledgers globais (Claude Code e Codex) ficam separados. Foi decisão do Leo em
  04/08/2026, e o validador recusa rebaixar um deles. Não reabra.
- Não reconstrua `dist/` de uma versão publicada sem refazer os checksums no documento da
  release.
- No Windows, `write_text` troca `\n` por `\r\n` e quebra o build reproduzível. Ao reescrever
  arquivo do projeto por script, passe `newline="\n"`.
- Não afirme conformidade regulatória nem chame o ledger de inviolável. O plugin já é
  cuidadoso com esses dois limites e a revisão não pode afrouxá-los.

## 7. Pronto quando

A fase 1 termina quando cada pergunta da seção 3 tem resposta com evidência ou uma lacuna
nomeada, e o Leo decidiu nome, escopo e corte. A fase 2 termina quando cada item aprovado está
mergeado com as três suítes verdes e um CI que as mantém assim, a Skill passa nos casos de
ativação em sessão limpa, o caminho principal foi exercitado de novo com um material real depois
das mudanças, e o que depende de publicação está listado como pergunta ao Leo, não como aviso.
