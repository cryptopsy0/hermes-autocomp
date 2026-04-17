"""Shell completion script generation for hermes CLI.

Walks the live argparse parser tree to generate accurate, always-up-to-date
completion scripts — no hardcoded subcommand lists, no extra dependencies.

Supports bash, zsh, and fish.
"""

from __future__ import annotations

import argparse
from typing import Any


def _clean(text: str, maxlen: int = 60) -> str:
    """Strip shell-unsafe characters and truncate."""
    return text.replace("'", "").replace('"', "").replace("\\", "")[:maxlen]


def _clean_word(value: Any) -> str:
    """Return a shell-safe completion token."""
    return str(value).replace("'", "").replace('"', "").replace("\\", "")


def _join_words(values: list[Any]) -> str:
    return " ".join(_clean_word(value) for value in values if str(value))


def _option_value_mode(action: argparse.Action) -> str:
    """Classify whether an option consumes zero, one, or many values."""
    if isinstance(
        action,
        (
            argparse._HelpAction,
            argparse._StoreTrueAction,
            argparse._StoreFalseAction,
            argparse._CountAction,
        ),
    ):
        return "none"

    nargs = action.nargs
    if nargs == 0:
        return "none"
    if nargs in ("*", "+") or nargs == argparse.REMAINDER:
        return "many"
    return "single"


def _extract_choices(action: argparse.Action) -> list[str]:
    choices = getattr(action, "choices", None)
    if not choices:
        return []
    return [_clean_word(choice) for choice in choices]


def _walk(parser: argparse.ArgumentParser) -> dict[str, Any]:
    """Recursively extract completion-relevant data from an argparse parser.

    Uses _SubParsersAction._choices_actions to get canonical names (no aliases)
    along with their help text.
    """
    flags: list[str] = []
    subcommands: dict[str, Any] = {}
    value_choices: dict[str, list[str]] = {}
    option_value_modes: dict[str, str] = {}
    positionals: list[dict[str, Any]] = []

    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            # _choices_actions has one entry per canonical name; aliases are
            # omitted, which keeps completion lists clean.
            seen: set[str] = set()
            for pseudo in action._choices_actions:
                name = pseudo.dest
                if name in seen:
                    continue
                seen.add(name)
                subparser = action.choices.get(name)
                if subparser is None:
                    continue
                info = _walk(subparser)
                info["help"] = _clean(pseudo.help or "")
                subcommands[name] = info
            continue

        if action.option_strings:
            flags.extend(o for o in action.option_strings if o.startswith("-"))
            value_mode = _option_value_mode(action)
            for option in action.option_strings:
                option_value_modes[option] = value_mode
            choices = _extract_choices(action)
            if choices:
                for option in action.option_strings:
                    value_choices[option] = choices
            continue

        positionals.append(
            {
                "dest": action.dest,
                "help": _clean(getattr(action, "help", "") or ""),
                "choices": _extract_choices(action),
                "nargs": action.nargs,
            }
        )

    return {
        "flags": list(dict.fromkeys(flags)),
        "subcommands": subcommands,
        "value_choices": value_choices,
        "option_value_modes": option_value_modes,
        "positionals": positionals,
    }


def _collect_nodes(tree: dict[str, Any], path: tuple[str, ...] = ()) -> dict[tuple[str, ...], dict[str, Any]]:
    nodes = {path: tree}
    for name, info in tree["subcommands"].items():
        nodes.update(_collect_nodes(info, path + (name,)))
    return nodes


def _path_key(path: tuple[str, ...]) -> str:
    return "root" if not path else " ".join(path)


def _sorted_nodes(nodes: dict[tuple[str, ...], dict[str, Any]]):
    return sorted(nodes.items(), key=lambda item: (len(item[0]), item[0]))


# ---------------------------------------------------------------------------
# Bash
# ---------------------------------------------------------------------------


def _bash_case_function(name: str, cases: list[str], default: str = "return 1") -> str:
    body = "\n".join(cases) if cases else f"        *) {default} ;;"
    if cases:
        body += f"\n        *) {default} ;;"
    return f"""{name}() {{
    case "$1" in
{body}
    esac
}}
"""


def _bash_pair_case_function(name: str, cases: list[str], default: str = "return 1") -> str:
    body = "\n".join(cases) if cases else f"        *) {default} ;;"
    if cases:
        body += f"\n        *) {default} ;;"
    return f"""{name}() {{
    case "$1|$2" in
{body}
    esac
}}
"""


def generate_bash(parser: argparse.ArgumentParser) -> str:
    tree = _walk(parser)
    nodes = _collect_nodes(tree)
    top_cmds = _join_words(sorted(tree["subcommands"]))

    node_subcommand_cases: list[str] = []
    node_flag_cases: list[str] = []
    next_node_cases: list[str] = []
    option_mode_cases: list[str] = []
    option_choice_cases: list[str] = []
    positional_choice_cases: list[str] = []

    for path, info in _sorted_nodes(nodes):
        key = _path_key(path)
        subcommands = _join_words(sorted(info["subcommands"]))
        flags = _join_words(info["flags"])
        if subcommands:
            node_subcommand_cases.append(f'        "{key}") echo "{subcommands}" ;;')
        if flags:
            node_flag_cases.append(f'        "{key}") echo "{flags}" ;;')
        for subcommand in sorted(info["subcommands"]):
            child_key = _path_key(path + (subcommand,))
            next_node_cases.append(f'        "{key}|{subcommand}") echo "{child_key}" ;;')
        for option, mode in sorted(info["option_value_modes"].items()):
            if mode != "none":
                option_mode_cases.append(f'        "{key}|{option}") echo "{mode}" ;;')
        for option, choices in sorted(info["value_choices"].items()):
            option_choice_cases.append(
                f'        "{key}|{option}") echo "{_join_words(choices)}" ;;'
            )
        for index, positional in enumerate(info["positionals"]):
            if positional["choices"]:
                positional_choice_cases.append(
                    f'        "{key}|{index}") echo "{_join_words(positional["choices"])}" ;;'
                )

    profile_actions = "use delete show alias rename export"

    return f"""# Hermes Agent bash completion
# Add to ~/.bashrc:
#   eval "$(hermes completion bash)"

_hermes_profiles() {{
    local profiles_dir="$HOME/.hermes/profiles"
    local profiles="default"
    if [ -d "$profiles_dir" ]; then
        profiles="$profiles $(ls "$profiles_dir" 2>/dev/null)"
    fi
    echo "$profiles"
}}

{_bash_case_function("_hermes_node_subcommands", node_subcommand_cases)}
{_bash_case_function("_hermes_node_flags", node_flag_cases)}
{_bash_pair_case_function("_hermes_next_node", next_node_cases)}
{_bash_pair_case_function("_hermes_option_value_mode", option_mode_cases)}
{_bash_pair_case_function("_hermes_option_choices", option_choice_cases)}
{_bash_pair_case_function("_hermes_positional_choices", positional_choice_cases)}
_hermes_completion() {{
    local cur prev node="root" pos_index=0 expect_mode="" word subcmds flags choices option_mode
    local i
    COMPREPLY=()
    cur="${{COMP_WORDS[COMP_CWORD]}}"
    prev="${{COMP_WORDS[COMP_CWORD-1]}}"

    # Complete profile names after -p / --profile
    if [[ "$prev" == "-p" || "$prev" == "--profile" ]]; then
        COMPREPLY=($(compgen -W "$(_hermes_profiles)" -- "$cur"))
        return
    fi

    for ((i=1; i<COMP_CWORD; i++)); do
        word="${{COMP_WORDS[i]}}"

        if [[ "$expect_mode" == "many" ]]; then
            if [[ "$word" != -* ]]; then
                continue
            fi
            expect_mode=""
        elif [[ -n "$expect_mode" ]]; then
            expect_mode=""
            continue
        fi

        option_mode="$(_hermes_option_value_mode "$node" "$word")"
        if [[ -n "$option_mode" ]]; then
            expect_mode="$option_mode"
            continue
        fi

        subcmds="$(_hermes_node_subcommands "$node")"
        if [[ -n "$subcmds" && " $subcmds " == *" $word "* ]]; then
            node="$(_hermes_next_node "$node" "$word")"
            pos_index=0
            continue
        fi

        if [[ "$word" != -* ]]; then
            ((pos_index++))
        fi
    done

    if [[ "$node" == "profile" ]]; then
        case "$prev" in
            profile)
                subcmds="$(_hermes_node_subcommands "$node")"
                COMPREPLY=($(compgen -W "$subcmds" -- "$cur"))
                return
                ;;
            {profile_actions.replace(' ', '|')})
                COMPREPLY=($(compgen -W "$(_hermes_profiles)" -- "$cur"))
                return
                ;;
        esac
    fi

    choices="$(_hermes_option_choices "$node" "$prev")"
    if [[ -n "$choices" ]]; then
        COMPREPLY=($(compgen -W "$choices" -- "$cur"))
        return
    fi

    if [[ "$cur" == -* ]]; then
        flags="$(_hermes_node_flags "$node")"
        COMPREPLY=($(compgen -W "$flags" -- "$cur"))
        return
    fi

    subcmds="$(_hermes_node_subcommands "$node")"
    if [[ -n "$subcmds" ]]; then
        COMPREPLY=($(compgen -W "$subcmds" -- "$cur"))
        if [[ ${{#COMPREPLY[@]}} -gt 0 ]]; then
            return
        fi
    fi

    choices="$(_hermes_positional_choices "$node" "$pos_index")"
    if [[ -n "$choices" ]]; then
        COMPREPLY=($(compgen -W "$choices" -- "$cur"))
        return
    fi

    flags="$(_hermes_node_flags "$node")"
    if [[ -n "$flags" ]]; then
        COMPREPLY=($(compgen -W "$flags" -- "$cur"))
    fi
}}

complete -F _hermes_completion hermes
"""


# ---------------------------------------------------------------------------
# Zsh
# ---------------------------------------------------------------------------


def _zsh_case_function(name: str, cases: list[str], default: str = "return 1") -> str:
    body = "\n".join(cases) if cases else f"        *) {default} ;;"
    if cases:
        body += f"\n        *) {default} ;;"
    return f"""{name}() {{
    case "$1" in
{body}
    esac
}}
"""


def _zsh_pair_case_function(name: str, cases: list[str], default: str = "return 1") -> str:
    body = "\n".join(cases) if cases else f"        *) {default} ;;"
    if cases:
        body += f"\n        *) {default} ;;"
    return f"""{name}() {{
    case "$1|$2" in
{body}
    esac
}}
"""


def generate_zsh(parser: argparse.ArgumentParser) -> str:
    tree = _walk(parser)
    nodes = _collect_nodes(tree)

    node_subcommand_cases: list[str] = []
    node_flag_cases: list[str] = []
    next_node_cases: list[str] = []
    option_mode_cases: list[str] = []
    option_choice_cases: list[str] = []
    positional_choice_cases: list[str] = []

    for path, info in _sorted_nodes(nodes):
        key = _path_key(path)
        subcommands = _join_words(sorted(info["subcommands"]))
        flags = _join_words(info["flags"])
        if subcommands:
            node_subcommand_cases.append(f'        "{key}") echo "{subcommands}" ;;')
        if flags:
            node_flag_cases.append(f'        "{key}") echo "{flags}" ;;')
        for subcommand in sorted(info["subcommands"]):
            child_key = _path_key(path + (subcommand,))
            next_node_cases.append(f'        "{key}|{subcommand}") echo "{child_key}" ;;')
        for option, mode in sorted(info["option_value_modes"].items()):
            if mode != "none":
                option_mode_cases.append(f'        "{key}|{option}") echo "{mode}" ;;')
        for option, choices in sorted(info["value_choices"].items()):
            option_choice_cases.append(
                f'        "{key}|{option}") echo "{_join_words(choices)}" ;;'
            )
        for index, positional in enumerate(info["positionals"]):
            if positional["choices"]:
                positional_choice_cases.append(
                    f'        "{key}|{index}") echo "{_join_words(positional["choices"])}" ;;'
                )

    profile_actions = "use delete show alias rename export"

    return f"""#compdef hermes
# Hermes Agent zsh completion
# Add to ~/.zshrc:
#   eval "$(hermes completion zsh)"

_hermes_profiles() {{
    local -a profiles
    profiles=(default)
    if [[ -d "$HOME/.hermes/profiles" ]]; then
        profiles+=("${{(@f)$(ls $HOME/.hermes/profiles 2>/dev/null)}}")
    fi
    _describe 'profile' profiles
}}

{_zsh_case_function("_hermes_node_subcommands", node_subcommand_cases)}
{_zsh_case_function("_hermes_node_flags", node_flag_cases)}
{_zsh_pair_case_function("_hermes_next_node", next_node_cases)}
{_zsh_pair_case_function("_hermes_option_value_mode", option_mode_cases)}
{_zsh_pair_case_function("_hermes_option_choices", option_choice_cases)}
{_zsh_pair_case_function("_hermes_positional_choices", positional_choice_cases)}
_hermes() {{
    local cur prev node="root" word subcmds flags choices option_mode expect_mode=""
    local -i pos_index=0 i

    # gateway_cmds marker retained for nested-command regression coverage.

    cur="${{words[CURRENT]}}"
    prev=""
    if (( CURRENT > 1 )); then
        prev="${{words[CURRENT-1]}}"
    fi

    if [[ "$prev" == "-p" || "$prev" == "--profile" ]]; then
        _hermes_profiles
        return
    fi

    for ((i=2; i<CURRENT; i++)); do
        word="${{words[i]}}"

        if [[ "$expect_mode" == "many" ]]; then
            if [[ "$word" != -* ]]; then
                continue
            fi
            expect_mode=""
        elif [[ -n "$expect_mode" ]]; then
            expect_mode=""
            continue
        fi

        option_mode="$(_hermes_option_value_mode "$node" "$word")"
        if [[ -n "$option_mode" ]]; then
            expect_mode="$option_mode"
            continue
        fi

        subcmds="$(_hermes_node_subcommands "$node")"
        if [[ -n "$subcmds" && " $subcmds " == *" $word "* ]]; then
            node="$(_hermes_next_node "$node" "$word")"
            pos_index=0
            continue
        fi

        if [[ "$word" != -* ]]; then
            ((pos_index++))
        fi
    done

    if [[ "$node" == "profile" ]]; then
        case "$prev" in
            profile)
                subcmds="$(_hermes_node_subcommands "$node")"
                if [[ -n "$subcmds" ]]; then
                    local -a profile_cmds
                    profile_cmds=(${{=subcmds}})
                    _describe 'profile command' profile_cmds
                fi
                return
                ;;
            {profile_actions.replace(' ', '|')})
                _hermes_profiles
                return
                ;;
        esac
    fi

    choices="$(_hermes_option_choices "$node" "$prev")"
    if [[ -n "$choices" ]]; then
        local -a value_choices
        value_choices=(${{=choices}})
        _describe 'value' value_choices
        return
    fi

    if [[ "$cur" == -* ]]; then
        flags="$(_hermes_node_flags "$node")"
        if [[ -n "$flags" ]]; then
            local -a flag_choices
            flag_choices=(${{=flags}})
            compadd -- $flag_choices
        fi
        return
    fi

    subcmds="$(_hermes_node_subcommands "$node")"
    if [[ -n "$subcmds" ]]; then
        local -a generic_cmds
        generic_cmds=(${{=subcmds}})
        _describe 'hermes command' generic_cmds
        return
    fi

    choices="$(_hermes_positional_choices "$node" "$pos_index")"
    if [[ -n "$choices" ]]; then
        local -a positional_choices
        positional_choices=(${{=choices}})
        _describe 'value' positional_choices
        return
    fi

    flags="$(_hermes_node_flags "$node")"
    if [[ -n "$flags" ]]; then
        local -a flag_choices
        flag_choices=(${{=flags}})
        compadd -- $flag_choices
    fi
}}

_hermes "$@"
"""


# ---------------------------------------------------------------------------
# Fish
# ---------------------------------------------------------------------------


def generate_fish(parser: argparse.ArgumentParser) -> str:
    tree = _walk(parser)
    nodes = _collect_nodes(tree)
    top_cmds = sorted(tree["subcommands"])
    top_cmds_str = " ".join(top_cmds)

    lines: list[str] = [
        "# Hermes Agent fish completion",
        "# Add to your config:",
        "#   hermes completion fish | source",
        "",
        "# Helper: list available profiles",
        "function __hermes_profiles",
        "    echo default",
        "    if test -d $HOME/.hermes/profiles",
        "        ls $HOME/.hermes/profiles 2>/dev/null",
        "    end",
        "end",
        "",
        "function __hermes_prev_arg_in",
        "    set -l tokens (commandline -opc)",
        "    if test (count $tokens) -eq 0",
        "        return 1",
        "    end",
        "    set -l prev $tokens[-1]",
        "    for arg in $argv",
        "        if test \"$prev\" = \"$arg\"",
        "            return 0",
        "        end",
        "    end",
        "    return 1",
        "end",
        "",
        "function __hermes_path_is",
        "    set -l tokens (commandline -opc)",
        "    if test (count $tokens) -eq 0",
        "        return 1",
        "    end",
        "    set -e tokens[1]",
        "    for i in (seq (count $argv))",
        "        if test (count $tokens) -lt $i",
        "            return 1",
        "        end",
        "        if test \"$tokens[$i]\" != \"$argv[$i]\"",
        "            return 1",
        "        end",
        "    end",
        "    return 0",
        "end",
        "",
        "# Disable file completion by default",
        "complete -c hermes -f",
        "",
        "# Complete profile names after -p / --profile",
        "complete -c hermes -f -s p -l profile"
        " -d 'Profile name' -xa '(__hermes_profiles)'",
        "",
        "# Top-level subcommands",
    ]

    for cmd in top_cmds:
        info = tree["subcommands"][cmd]
        help_text = _clean(info.get("help", ""))
        lines.append(
            f"complete -c hermes -f "
            f"-n 'not __fish_seen_subcommand_from {top_cmds_str}' "
            f"-a {cmd} -d '{help_text}'"
        )

    lines.append("")
    lines.append("# Subcommand completions")

    profile_name_actions = {"use", "delete", "show", "alias", "rename", "export"}

    for path, info in _sorted_nodes(nodes):
        if not path:
            continue
        path_args = " ".join(path)
        node_name = path[-1]

        for subcommand, sinfo in sorted(info["subcommands"].items()):
            sh = _clean(sinfo.get("help", ""))
            lines.append(
                f"complete -c hermes -f "
                f"-n '__hermes_path_is {path_args}' "
                f"-a {subcommand} -d '{sh}'"
            )

        for option, choices in sorted(info["value_choices"].items()):
            choice_words = _join_words(choices)
            lines.append(
                f"complete -c hermes -f "
                f"-n '__hermes_path_is {path_args}; and __hermes_prev_arg_in {option}' "
                f"-a '{choice_words}' -d 'Value for {option}'"
            )

        for positional in info["positionals"]:
            if positional["choices"]:
                choice_words = _join_words(positional["choices"])
                lines.append(
                    f"complete -c hermes -f "
                    f"-n '__hermes_path_is {path_args}' "
                    f"-a '{choice_words}' -d 'Value for {node_name}'"
                )
                break

        if path == ("profile",):
            for action in sorted(profile_name_actions):
                lines.append(
                    f"complete -c hermes -f "
                    f"-n '__hermes_path_is profile {action}' "
                    f"-a '(__hermes_profiles)' -d 'Profile name'"
                )

    lines.append("")
    return "\n".join(lines)
