# Unquoted list boundary
A comma outside quotes separates values in a flow list. Accept the existing unquoted [AGENTS.md, docs/a.md] form.

# Quoted value boundary
A comma inside quotes is literal content, not a separator; the writer emits JSON-style quoted strings/escapes. A multiline scalar list has the same semantics. Complex nested objects are unsupported and must fail clearly before writing.
