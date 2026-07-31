# Ledger encadeado por hash (0.6.0)

Status: PROPOSTO 2026-07-31 — aguarda deliberação
Target version: 0.6.0
Fecha: a lacuna mais embaraçosa de uma ferramenta de auditoria — o próprio rastro é editável sem
deixar vestígio

## 1. O problema

O ledger é um arquivo JSON. Qualquer processo com permissão de escrita pode reescrever um
`authorization.quote`, mudar o `result` de um `RUN`, ou apagar um record inteiro, e **nada** no
sistema percebe. `verify` valida forma, referências e sequências; nenhuma dessas checagens nota
que um registro válido foi trocado por outro registro válido.

Isso importa mais aqui do que em quase qualquer outro arquivo, porque o valor inteiro do produto
é a frase "este é o registro do que foi autorizado e feito". Um registro que pode ser reescrito
silenciosamente sustenta essa frase só enquanto ninguém a testa.

Precedente de mercado: o Agent Governance Toolkit da Microsoft trata evidência de auditoria com
cadeia Merkle exatamente por esse motivo.

## 2. Ameaça — e o limite honesto

O que a cadeia entrega é **evidência de adulteração** (tamper-evident), não **impossibilidade de
adulteração** (tamper-proof).

| Cenário | Detectado? |
|---|---|
| Editar um record e salvar | **Sim** — digest do record não bate |
| Apagar um record do meio | **Sim** — `previous` do seguinte não bate |
| Reordenar records | **Sim** — índice/encadeamento quebra |
| Truncar o fim da cadeia | **Só com âncora externa** (§3.4) |
| Reescrever tudo e recomputar a cadeia inteira | **Não** — sem âncora externa |

Essa tabela vai para `references/LEDGER.md` literalmente. Uma ferramenta de auditoria que
exagera a própria garantia é pior do que uma que não tem nenhuma, porque induz confiança que ela
não sustenta.

## 3. Desenho

### 3.1 O campo

Cada entrada de `records[]` ganha um objeto `chain`:

```json
"chain": {
  "index": 7,
  "previous": "sha256:…",   // digest do record anterior; null no primeiro
  "digest":   "sha256:…"    // digest deste record
}
```

### 3.2 Canonicalização

`digest` = SHA-256 dos bytes UTF-8 de `json.dumps(record_sem_chain_digest, sort_keys=True,
separators=(",", ":"), ensure_ascii=False)`.

`chain.digest` é removido antes de hashear; `chain.index` e `chain.previous` **entram** no hash,
que é o que amarra a posição do record à sua identidade. A disciplina de serialização é a que
`serialize_payload` já usa para o payload do dashboard — chaves ordenadas, separadores compactos —
e é reusada, não reimplementada, porque duas canonicalizações acabam divergindo.

Ordem da cadeia é a ordem do array `records[]`, não a data: datas são conteúdo, editável;
posição no array é estrutura.

### 3.3 `verify --chain`

Recomputa cada digest, confere cada `previous`, confere que `index` é 0,1,2,… sem buraco.
Relatório por record e um veredito por ledger. Vocabulário fechado, no estilo de `DRIFT_REASONS`:
`digest_mismatch`, `previous_mismatch`, `index_gap`, `unchained`.

**Compatibilidade é obrigatória.** O ledger vivo já tem records sem `chain`. Um record sem o
campo é `unchained` — sem cadeia, e portanto sem garantia — e isso é **achado sob `--chain`,
silêncio sem a flag**. Nunca inválido: transformar todo ledger existente em documento inválido
seria destruir o registro que o produto existe para preservar.

Uma cadeia que começa não encadeada e passa a encadeada a partir de um ponto é legítima e é o
estado normal pós-migração. O primeiro record encadeado tem `previous: null`.

### 3.4 Âncora externa

O elo que fecha a linha "reescrever tudo" da tabela §2 não pode morar no mesmo arquivo. Portanto:

```text
dashboard.py chain --head <ledger>
```

imprime o digest da cabeça da cadeia, e nada mais, para ser fixado **fora** do ledger: mensagem
de commit, tag git, anotação em outro sistema. `verify --chain --expect-head <digest>` confere.

Isto é deliberadamente humilde: não há chave, não há assinatura, não há serviço. É um número que
o usuário guarda noutro lugar — e é o suficiente para transformar "reescreveram tudo" de
indetectável em detectável.

### 3.5 Selagem

```text
dashboard.py chain --seal <ledger>
```

escreve `chain` nos records que não têm. É o **segundo** comando que escreve arquivo, depois de
`build`, e por isso: exige que `verify` passe antes, escreve por `os.replace` como `build` já faz,
recusa-se a operar se qualquer `chain` existente já estiver quebrada (selar por cima de
adulteração é apagar a prova), e imprime a cabeça resultante.

A Skill passa a selar após cada escrita de ledger, como já roda `verify`. Selar é escrituração,
não implementação — mesma isenção que `LEDGER.md` já concede à escrita do ledger.

## 4. O que isto não faz

- Não assina nada. Assinatura (Sigstore/Ed25519) traz gestão de chave e fica para depois, opcional.
- Não usa árvore de Merkle: a estrutura é linear, e uma árvore só pagaria por prova de inclusão
  parcial, que ninguém aqui pediu.
- Não encadeia `baselines[]` nem `backlog[]` nesta passagem — `records[]` é onde moram
  autorização e resultado, que é o que se adultera com proveito.
- Não impede escrita. Nada aqui é controle de acesso.

## 5. Aceitação

1. Digest é estável entre duas execuções e entre plataformas (mesma canonicalização).
2. Editar um byte de qualquer campo de um record quebra `--chain` naquele record.
3. Apagar um record do meio quebra o `previous` do seguinte.
4. Reordenar dois records quebra a cadeia.
5. Record sem `chain` é `unchained` — achado sob `--chain`, silêncio sem a flag; nunca inválido.
6. Ledger parcialmente selado verifica limpo a partir do primeiro record encadeado.
7. `--seal` recusa ledger que não passa em `verify`, e recusa selar por cima de cadeia quebrada.
8. `--seal` escreve exatamente um arquivo, por `os.replace`, preservando formato e fim de linha.
9. `--expect-head` detecta reescrita completa da cadeia.
10. A tabela de ameaças do §2 aparece literalmente em `references/LEDGER.md`.
