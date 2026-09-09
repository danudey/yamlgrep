#!/usr/bin/env python3

# stdlib imports
import re
import sys
import pathlib
import argparse

# from ... stdlib imports
from enum import StrEnum, auto
from types import GeneratorType
from typing import Optional

# third-party imports
import yaml
# from ... third-party imports
from rich.color import ColorSystem
from rich.console import Console
from rich_argparse import RawDescriptionRichHelpFormatter

description = """
yamlgrep is a simple tool to iterate through a yaml file and find ("grep")
for a pattern, returning not only the match but the path to the match as well.

The output format is similar to grep, though instead of `filename:lineno: matchingline`
we output `filename:docno: nodepath matchingval` where `docno` is the number of the
document within the file (if there are multiple) and nodepath is the path to the node
where the value was found (in yq-compatible syntax, e.g. .1.foo.bar.12).

By default only values are searched; pass `-k` to match key names as well, or
`--match keys` to match key names only. A key matches if any key in the path to
a value matches the pattern, so `--match keys labels` will show everything
underneath any `labels` key. Pass `--last-key` to match only the last key in
the path, so that `--last-key name` matches `.metadata.name` but not
`.metadata.name.first`.

Multiple files can be specified on the command line; if none are provided, the default
is to read from stdin. If you want to read from one or more files *and* stdin, pass `-`
as a filename. Each file will only be processed once.

Note that due to how yaml files can contain multi-line values, regular expression wildcards
like `.*` will always perform multi-line matches.
"""

console = Console(highlight=False)


class ShowFilename(StrEnum):
    AUTO = auto()
    ALWAYS = auto()
    NEVER = auto()


class ShowDocumentNumber(StrEnum):
    AUTO = auto()
    ALWAYS = auto()
    NEVER = auto()


class UseColour(StrEnum):
    AUTO = auto()
    ALWAYS = auto()
    NEVER = auto()


class MatchIn(StrEnum):
    VALUES = auto()
    KEYS = auto()
    BOTH = auto()


# Which keys in the path a key match can be satisfied by: any of them, or only
# the last (i.e. the key the value itself hangs off).
class KeyScope(StrEnum):
    ANY = auto()
    LAST = auto()


# Along with the path and the value we yield the dictionary keys which make up
# that path, as a list of (offset, key) pairs, where `offset` is the position of
# that key within the path string. List indices aren't keys, so they're not
# included; this lets us match (and highlight) only the parts of a path which
# are actually key names.
def handle_obj(obj, path="", keys=()):
    if isinstance(obj, (list, GeneratorType)):
        for k, val in enumerate(obj):
            new_path = f"{path}.{k}"
            yield from handle_obj(val, new_path, keys)
    elif isinstance(obj, dict):
        for k, val in obj.items():
            key = str(k)
            new_path = f"{path}.{key}"
            yield from handle_obj(val, new_path, (*keys, (len(path) + 1, key)))
    elif isinstance(obj, (str, int, float, bool)):
        yield path, keys, obj
    elif obj is None:
        yield path, keys, obj
    else:
        raise ValueError(f"Got unhandled type {type(obj)} at path {path}")


def iter_files(files, recurse=False):
    if files:
        matching_files = set()
        for filename in files:
            if filename in matching_files:
                continue
            matching_files.add(filename)
            if filename == "-":
                if sys.stdin.isatty():
                    print(
                        f"yamlparse: reading from stdin but it's a tty?",
                        file=sys.stderr,
                    )
                yield "<stdin>", sys.stdin
            else:
                path = pathlib.Path(filename)
                if not path.exists():
                    print(
                        f"yamlparse: {filename}: No such file or directory",
                        file=sys.stderr,
                    )
                    continue
                if path.is_socket():
                    print(
                        f"yamlparse: {filename}: Can't grep sockets",
                        file=sys.stderr,
                    )
                    continue
                if path.is_dir():
                    if recurse:
                        for sub_file in path.glob("**/*.yml"):
                            yield sub_file.as_posix(), sub_file.open()
                        for sub_file in path.glob("**/*.yaml"):
                            yield sub_file.as_posix(), sub_file.open()
                    else:
                        print(f"yamlparse: skipping directory {path}", file=sys.stderr)
                    continue
                yield filename, path.open()
    else:
        if sys.stdin.isatty():
            print(f"yamlparse: reading from stdin but it's a tty?", file=sys.stderr)
        yield "<stdin>", sys.stdin


def match_bool(needle: str, haystack: bool) -> bool:
    if needle.lower() in ("true", "yes", "on"):
        needle_val = True
    elif needle.lower() in ("false", "no", "off"):
        needle_val = False
    else:
        return False
    return needle_val == haystack


def match_fixed(
    needle: str, haystack: str | int | float | bool, case_insensitive=False
) -> Optional[str]:
    stack_str = str(haystack)
    if isinstance(haystack, bool):
        result = match_bool(needle, haystack)
        if result:
            return needle

    if case_insensitive:
        if needle.lower() in stack_str.lower():
            return needle
    else:
        if needle in stack_str:
            return needle


# Note that we insert colours here in every case, but if our Console()
# is configured not to use colours they won't be output
def match_regexp(
    needle: str, haystack: str | int | float | bool, case_insensitive=False
) -> Optional[str]:
    if isinstance(haystack, bool):
        result = match_bool(needle, haystack)
        if result:
            return str(haystack)

    haystr = str(haystack)

    flags = re.MULTILINE | re.DOTALL
    if case_insensitive:
        flags = flags | re.IGNORECASE
    pat = re.compile(needle, flags)
    if res := pat.search(haystr):
        start, end = res.span()
        groups = []
        groups.append(haystr[:start])
        groups.append("[red]")
        groups.append(haystr[start:end])
        groups.append("[/red]")
        groups.append(haystr[end:])

        return "".join(groups)


# Keys are always strings, so we can highlight the matching part of the key
# itself rather than relying on what the value matchers hand back.
def match_key(
    needle: str, key: str, fixed_strings=False, case_insensitive=False
) -> Optional[str]:
    if fixed_strings:
        haystack = key.lower() if case_insensitive else key
        pattern = needle.lower() if case_insensitive else needle
        start = haystack.find(pattern)
        if start < 0:
            return None
        end = start + len(pattern)
    else:
        flags = re.MULTILINE | re.DOTALL
        if case_insensitive:
            flags = flags | re.IGNORECASE
        res = re.compile(needle, flags).search(key)
        if not res:
            return None
        start, end = res.span()

    return f"{key[:start]}[red]{key[start:end]}[/red]{key[end:]}"


# Replace each matching key in the path with its highlighted version; we work
# from the end of the path backwards so that the offsets stay valid as we go.
def highlight_path(path: str, key_matches: list[tuple[int, str, str]]) -> str:
    for start, key, highlighted in reversed(key_matches):
        path = f"{path[:start]}{highlighted}{path[start + len(key):]}"
    return path


def main():
    show_fnames = False
    had_data = False
    is_tty = sys.stdout.isatty()
    parser = argparse.ArgumentParser(
        "yamlgrep",
        description=description,
        formatter_class=RawDescriptionRichHelpFormatter,
        conflict_handler="resolve",
    )

    parser.set_defaults(
        show_filename=ShowFilename.AUTO, show_doc_number=ShowDocumentNumber.AUTO
    )

    parser.add_argument(
        "-f",
        "--fixed-strings",
        action="store_true",
        default=False,
        help="Pattern is a fixed string",
    )

    parser.add_argument(
        "-i",
        "--case-insensitive",
        action="store_true",
        default=False,
        help="Do a case-insensitive match",
    )

    # Whether to match against values, key names, or both. `-k` is a shorthand
    # for `--match both`, since matching keys *as well as* values is the common
    # case; note that -k can't take an optional value of its own, since argparse
    # would then swallow the pattern (`yamlgrep -k foo`) as that value.
    # match_in defaults to None so that we can tell later whether it was given
    # explicitly; --last-key implies matching keys if it wasn't.
    parser.set_defaults(match_in=None, key_scope=KeyScope.ANY)

    parser.add_argument(
        "--match",
        dest="match_in",
        choices=MatchIn,
        metavar="WHAT",
        help=f"What to match the pattern against; WHAT is one of ({', '.join(MatchIn)}) (default: {MatchIn.VALUES}, or {MatchIn.BOTH} if --last-key is given)",
    )

    parser.add_argument(
        "-k",
        "--keys",
        dest="match_in",
        action="store_const",
        const=MatchIn.BOTH,
        help=f"Match against key names as well as values (same as --match {MatchIn.BOTH})",
    )

    # Whether a key match can come from anywhere in the path, or only from its
    # last component
    parser.add_argument(
        "--key-scope",
        choices=KeyScope,
        metavar="WHAT",
        help=f"Which part of the path a key match can come from; WHAT is one of ({', '.join(KeyScope)}) (default: {KeyScope.ANY})",
    )

    parser.add_argument(
        "--last-key",
        dest="key_scope",
        action="store_const",
        const=KeyScope.LAST,
        help=f"Only match the last component of a key path (same as --key-scope {KeyScope.LAST})",
    )

    # I hate when long-running scripts provide no output
    parser.add_argument(
        "--print-no-match",
        action="store_true",
        default=False,
        help="Print if a file did not contain a match",
    )

    # TODO: maybe we should default to searching recursively if no files are
    # specified and stdin is a tty?
    parser.add_argument(
        "-r",
        "--recurse",
        action="store_true",
        default=False,
        help="Descend into directories passed on the command-line",
    )

    # Whether or not to print the filename (default is to print it if there's more than one input)
    parser.add_argument(
        "-H",
        "--filename",
        dest="show_filename",
        choices=ShowFilename,
        metavar="WHEN",
        help=f"Show the filename for each matching line; WHEN is [{', '.join(ShowFilename)}]",
    )

    # Whether or not to show the document number (default is to print it if there's more than one document in the file)
    parser.add_argument(
        "-D",
        "--doc-number",
        dest="show_doc_number",
        choices=ShowDocumentNumber,
        metavar="WHEN",
        help=f"Show the number of the yaml document in multi-document files; WHEN is [{', '.join(ShowDocumentNumber)}]",
    )

    # Whether or not to use colour (default is to do so if output is a tty)
    parser.add_argument(
        "-c",
        "--color",
        "--colour",
        dest="use_color",
        choices=UseColour,
        metavar="WHEN",
        help=f"Whether or not to use colour to highlight matches; WHEN is [{', '.join(UseColour)}]",
    )

    # The pattern can be either a regexp or a fixed string
    parser.add_argument("pattern", help="The pattern to search for")

    # Zero or more input files - if no input is specified, read from stdin
    parser.add_argument(
        "input_files",
        nargs="*",
        default=[],
        help="Files to search through (default: read from stdin)",
    )

    args = parser.parse_args()

    match args.use_color:
        case UseColour.ALWAYS:
            console.no_color = False
            console._color_system = ColorSystem.STANDARD
        case UseColour.NEVER:
            console.no_color = True
        case UseColour.AUTO:
            pass

    match args.show_filename:
        case ShowFilename.ALWAYS:
            show_fnames = True
        case ShowFilename.NEVER:
            show_fnames = False
        case ShowFilename.AUTO:
            if len(args.input_files) > 1 or args.recurse:
                show_fnames = True

    match args.show_doc_number:
        case ShowDocumentNumber.ALWAYS:
            show_docno = True
        case ShowDocumentNumber.NEVER:
            show_docno = False
        case _:
            show_docno = None

    if args.fixed_strings:
        matcher = match_fixed
    else:
        matcher = match_regexp

    if args.match_in is None:
        if args.key_scope == KeyScope.LAST:
            args.match_in = MatchIn.BOTH
        else:
            args.match_in = MatchIn.VALUES

    match_values = args.match_in in (MatchIn.VALUES, MatchIn.BOTH)
    match_keys = args.match_in in (MatchIn.KEYS, MatchIn.BOTH)

    try:
        for filename, file_obj in iter_files(args.input_files, recurse=args.recurse):
            if had_data and is_tty:
                print()
            had_data = False
            data = list(yaml.safe_load_all(file_obj))
            if args.show_doc_number == ShowFilename.AUTO:
                show_docno = len(data) > 1

            doc_matched = False
            doc_was_matched = False

            for doc_no, document in enumerate(data):
                prefixes = []
                if show_fnames:
                    prefixes.append(f"[cyan]{filename}[/cyan]")
                if show_docno:
                    prefixes.append(f"[green]{str(doc_no)}[/green]")
                prefixes.append(" ")
                prefix = ":".join(prefixes).lstrip()

                doc_was_matched = doc_matched
                doc_matched = False
                try:
                    for path, keys, val in handle_obj(document):
                        res = None
                        if match_values:
                            res = matcher(
                                args.pattern,
                                val,
                                case_insensitive=args.case_insensitive,
                            )

                        key_matches = []
                        if match_keys:
                            if args.key_scope == KeyScope.LAST:
                                candidates = keys[-1:]
                            else:
                                candidates = keys
                            for offset, key in candidates:
                                if highlighted := match_key(
                                    args.pattern,
                                    key,
                                    fixed_strings=args.fixed_strings,
                                    case_insensitive=args.case_insensitive,
                                ):
                                    key_matches.append((offset, key, highlighted))

                        if res or key_matches:
                            had_data = True
                            if doc_was_matched and not doc_matched:
                                console.print("---")
                            doc_matched = True
                            out_path = highlight_path(path, key_matches)
                            out_val = res if res else str(val)
                            console.print(f"{prefix}[blue]{out_path}[/blue] {out_val}")
                except ValueError as ex:
                    print(
                        f"Error parsing file {filename} doc {doc_no}: {ex}",
                        file=sys.stderr,
                    )
            if args.print_no_match and not had_data:
                print(f"yamllint: file {filename} had no matches", file=sys.stderr)

    except KeyboardInterrupt:
        return


if __name__ == "__main__":
    main()
