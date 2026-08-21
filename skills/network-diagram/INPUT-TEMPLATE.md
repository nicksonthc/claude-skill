# Input template

Fill this in from what the user actually told you. **Leave a field blank and
ask rather than inventing a hostname, port, IP, revision or date.** A blank
field is a question; a guessed field is a drawing that lies.

**No secrets.** A spec row never holds a password, key or token — the sheet
gets screenshotted, mailed and committed. Record `AUTH : ssh · key-based` and
leave the secret in the vault. If the drawing may be published, use
documentation IPs (`192.0.2.0/24`, `198.51.100.0/24`) rather than real ones.

```
PROJECT NAME      : <e.g. EXAMPLE PLANT MATERIAL MGMT>
PROJECT CODE      : <e.g. DEMO-0001>
DRAWING DOMAIN    : <MFG | DATA | SECURITY | PLATFORM>
DRAWING NO        : <e.g. NWK-MFG-001>
REVISION          : <e.g. 1.2>
DATE              : <YYYY-MM-DD>
CLASSIFICATION    : <e.g. CLASSIFIED · INTERNAL>
THEME             : <cobalt | moss | charcoal>

ZONES (left-to-right, or grouped):
  - <ZONE NAME> — <one-line purpose>

NODES (one block per node):
  - id        : <short stable id, e.g. RHEL-APP-01>
    name      : <DISPLAY NAME>
    host      : <hostname or fqdn>
    zone      : <which zone above>
    tag       : <SERVER · APP HOST | CLIENT · OPERATOR | CLOUD · EXTERNAL | …>
    specs     :
      - <KEY> : <value>          # 3–6 rows
    children  :                  # optional — containers / daemons / pods
      - name  : <CONTAINER NAME>
        kind  : <container | daemon | pod | controller | vm>
        stack : <one-line description>
        ports :
          - <:port>  <TAG>       # e.g. :8080  API · HTTP
    internal  : <child A → child B :port · description>   # optional

FLOWS (numbered in display order):
  - from   : <node id, or node.child>
    to     : <node id, or node.child>
    style   : <solid | dashed | warm>
    proto   : <e.g. HTTP / 8082>
    desc    : <e.g. → React UI · MMS>

NOTES:
  - <physical constraints, must-route-around, special zone shapes, …>
```

## Style semantics

| `style`  | Stroke                        | Means                                      |
| -------- | ----------------------------- | ------------------------------------------ |
| `solid`  | `--accent`                    | production traffic                          |
| `dashed` | `--accent`, dasharray `8 5`   | admin / deployment / out-of-band query      |
| `warm`   | `--warm` (`#C25D34`)          | bootstrap / one-time / image pull           |

## Worked example

`examples/network-topology.html` is a rendered MFG-domain drawing on the
`cobalt` theme, with all identifiers fictional. Read its title block, zones
and flow pills to see how a filled-in version of the above turns into the
finished sheet.
