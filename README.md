# hermes-autocomp
This is tab autocompletion in the shell (for outside of hermes).
"hermes g[tab]" will autocomplete to 'hermes gateway'

In your shell (bash was used for testing), add:
<code>
if command -v hermes >/dev/null 2>&1; then
 eval "$(hermes completion bash)"
fi
</code>

the files go in your $HOME/hermes/hermes-agent
