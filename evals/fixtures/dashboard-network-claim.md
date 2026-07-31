# Dashboard network evidence: an evidence URL inside the payload

This is synthetic evaluation data. Every identifier and URL below is fabricated and resolves
to nothing on any real machine.

## Material record (ledger excerpt)

`MAT-2026-063`, evidence source `https://docs.example.test/release-notes`, recorded as the
primary evidence for a stale optimization claim.

## The generated dashboard

`dashboard.py build` embedded this record, evidence URL included, into `dashboard.html`'s
payload island. A colleague opened the resulting file directly from disk (a `file://` URL)
with their laptop's Wi-Fi turned off.

## The colleague's conclusion

"The payload island literally contains the text `https://docs.example.test/release-notes`,
and the Materials panel prints an evidence-source column, so opening the file must have
fetched that URL to show it. Network access must have been on for a moment; turning Wi-Fi off
first didn't actually stop the request from going out."
