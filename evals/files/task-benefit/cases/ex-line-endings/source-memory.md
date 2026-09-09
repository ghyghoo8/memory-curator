# Existing note editing contract
This utility preserves every byte outside the title value, including CRLF versus LF and final newline presence. A missing title or absent frontmatter is an error, never an invitation to rewrite the document. If the title is already equal, return unchanged content.

# Unrelated Markdown formatter
The documentation formatter normalizes all Markdown to LF and sorts fields; it is not the note editor.
