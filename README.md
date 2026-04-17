# hermes-autocomp
This is tab autocompletion for outside of hermes. Such as running "hermes gateway":   "hermes g[tab]" will autocomplete.

In your shell (bash was used for testing), add:

if command -v hermes >/dev/null 2>&1; then
 eval "$(hermes completion bash)"
fi
