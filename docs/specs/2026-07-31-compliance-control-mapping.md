# Mapeamento de controles de conformidade (antecipado de 0.9.0)

Status: PROPOSTO 2026-07-31 — aguarda deliberação
Target version: 0.7.0 (antecipado de 0.9.0 por causa da janela regulatória)
Fecha: a distância entre "o ledger já é o artefato que os reguladores pedem" e "alguém consegue
provar isso"

## 1. Por que agora

As obrigações de alto risco do EU AI Act aplicam-se a partir de **2 de agosto de 2026**. Os
artigos que importam descrevem, quase literalmente, o que este ledger já produz:

| Exigência | O que o ledger já tem |
|---|---|
| Art. 11 — documentação técnica | records `MAT`/`PROP`/`ADR` com evidência datada |
| Art. 12 — registro automático de eventos | `records[]` + `baselines[]`, com digests |
| Art. 13 — instruções de uso, supervisão humana | `authorization.quote` nas palavras do usuário |
| Art. 19 — retenção de logs (6 meses) | ledger append-oriented, com datas |
| ISO 42001 A.6.2.6 — registro de operação | o mesmo `records[]` |
| ISO 42001 A.7.3 — gestão de acesso | itens `permission-rule` do baseline |
| ISO 42001 A.8.1 — supervisão humana | `authorization`, `deviations`, `rollback` |
| ISO 42001 cl. 8.4 — avaliação de impacto | `SCOPE_AND_RISK` nas propostas |

Falta apenas o dicionário que traduz record → controle. O levantamento de mercado é direto nesse
ponto: "suporta o EU AI Act" sem mapeamento por controle é marketing.

## 2. A regra que governa tudo neste incremento

**A ferramenta nunca afirma conformidade.** Ela afirma, e só, que existe ou não existe artefato
correspondente a um controle. A diferença não é de estilo, é de responsabilidade: conformidade é
julgamento de auditor sobre um sistema inteiro, e uma ferramenta que a declara está mentindo
sobre a própria competência — exatamente o erro que o marcador `SELF-REPORTED` já existe para
evitar no dashboard.

Vocabulário fechado, três valores, nenhum deles "compliant":

- `EVIDENCE_PRESENT` — há artefato correspondente, e ele é nomeado.
- `EVIDENCE_PARTIAL` — há artefato, mas incompleto segundo a regra declarada.
- `EVIDENCE_ABSENT` — não há artefato correspondente neste ledger.

A saída carrega a frase, em toda execução: *este relatório inventaria evidência, não certifica
conformidade; a suficiência de cada artefato é julgamento do auditor.*

## 3. Desenho

### 3.1 Mapeamentos são dados declarados

Como adapters já são. Um arquivo por framework em
`assets/compliance/<framework>.json`, validado por schema, com `expires_on` — porque texto
regulatório muda e um mapeamento vencido é pior que nenhum:

```json
{
  "mapping_version": 1,
  "framework": "eu-ai-act",
  "title": "Regulamento (UE) 2024/1689",
  "expires_on": "2027-01-31",
  "source": "https://eur-lex.europa.eu/eli/reg/2024/1689/oj",
  "verified_on": "2026-07-31",
  "controls": [
    {
      "id": "art-12",
      "title": "Registro automático de eventos",
      "requires": { "collection": "records", "min_count": 1 },
      "note": "Cada record datado é um evento registrado ao longo do ciclo de vida."
    },
    {
      "id": "art-13",
      "title": "Supervisão humana documentada",
      "requires": { "collection": "records", "where": { "type": "RUN" },
                    "every": { "field": "authorization.quote", "non_empty": true } }
    }
  ]
}
```

O predicado é minúsculo de propósito — `min_count`, `where`, `every`, `field`, `non_empty` — e
avaliado por código próprio. Nada de expressão executável vinda de arquivo: um mapeamento é
conteúdo, e conteúdo não vira código, que é a mesma fronteira que a camada de path-safety já
defende.

### 3.2 O comando

```text
dashboard.py compliance <ledger> --framework eu-ai-act [--out <dir>]
```

Read-only sem `--out`. Relatório em stdout como JSON, notas e achados em stderr, exatamente como
`drift` e `rollback-preview` — a mesma separação de fluxos, pelo mesmo motivo.

Códigos de saída seguindo a casa: `0` sem `EVIDENCE_ABSENT`, `1` com qualquer ausência, `2` erro
de ferramenta (framework desconhecido, mapeamento vencido ou inválido, ledger ilegível).

`--out` escreve o **pacote de evidência**: o relatório, mais uma cópia de cada record citado,
mais o digest de cada arquivo copiado — um diretório que se entrega a um auditor sem anexar o
ledger inteiro. Terceiro comando que escreve, e o único que escreve mais de um arquivo; por isso
`--out` recusa diretório não vazio a menos que venha `--force`.

### 3.3 Retenção

O relatório reporta a data do record mais antigo e a janela exigida pelo framework (6 meses no
art. 19). Reporta, não impõe: apagar ou reter é decisão do usuário, e uma ferramenta de auditoria
que apaga registro por conta própria é uma contradição em termos.

### 3.4 Frameworks desta passagem

`eu-ai-act` e `iso-42001` completos; `nist-ai-rmf` e `owasp-agentic` ficam como arquivos de
mapeamento a escrever depois, no mesmo formato, sem mudança de código. Um framework por arquivo
é o que torna isso verdade.

## 4. O que isto não faz

- Não certifica, não pontua, não emite selo.
- Não avalia o *sistema de IA* do usuário — avalia o ledger deste plugin. Se o usuário governa
  três clientes e só registra um, o relatório reflete o ledger, e diz isso.
- Não substitui a avaliação de risco da cl. 8.2 da ISO 42001, que exige análise humana ligando
  risco a controle.
- Não emite ASBOM/CycloneDX: é vizinho, é 0.8.0, e é outro spec.

## 5. Aceitação

1. Mapeamento inválido, desconhecido ou **vencido** é erro de ferramenta (`2`), nunca relatório
   silencioso.
2. Predicado é avaliado por código; nenhuma string de mapeamento é executada ou interpolada.
3. Os três valores do vocabulário são os únicos emitidos; a palavra "compliant" não aparece em
   saída alguma.
4. A ressalva do §2 aparece em toda execução, inclusive com `--out`.
5. `RUN` sem `authorization.quote` produz `EVIDENCE_ABSENT` em `art-13` e `A.8.1`, nomeando o
   record.
6. Ledger limpo e completo produz `0`; um único controle ausente produz `1`.
7. `--out` recusa diretório não vazio sem `--force`; cada arquivo copiado tem digest registrado.
8. Retenção é reportada, nunca aplicada — nenhum caminho de código apaga record.
9. Texto de conformidade traduzido em `en`/`pt-BR`; IDs de controle permanecem canônicos.
