#!/usr/bin/env python3

# stdlib imports
import re
import sys
import pathlib
import argparse

# from ... stdlib imports
from enum import StrEnum, auto
from types import GeneratorType

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

Multiple files can be specified on the command line; if none are provided, the default
is to read from stdin. If you want to read from one or more files *and* stdin, pass `-`
as a filename. Each file will only be processed once.
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


def handle_obj(obj, path=""):
    if isinstance(obj, (list, GeneratorType)):
        for k, val in enumerate(obj):
            new_path = f"{path}.{k}"
            yield from handle_obj(val, new_path)
    elif isinstance(obj, dict):
        for k, val in obj.items():
            new_path = f"{path}.{k}"
            yield from handle_obj(val, new_path)
    elif isinstance(obj, (str, int, float, bool)):
        yield path, obj
    else:
        raise ValueError(f"Got unhandled type {type(obj)}")


def iter_files(files):
    if files:
        matching_files = set()
        for filename in files:
            if filename in matching_files:
                continue
            matching_files.add(filename)
            if filename == "-":
                yield "<stdin>", sys.stdin
            else:
                path = pathlib.Path(filename)
                if not path.exists():
                    print(
                        f"yamlparse: {filename}: No such file or directory",
                        file=sys.stderr,
                    )
                    continue
                if path.is_dir() or path.is_socket():
                    print(
                        f"yamlparse: {filename}: Target files must be actual files",
                        file=sys.stderr,
                    )
                    continue
                yield filename, path.open()
    else:
        yield "<stdin>", sys.stdin


def match_fixed(needle, haystack):
    if needle in haystack:
        return needle


def match_regexp(needle, haystack):
    pat = re.compile(needle)
    if res := pat.search(haystack):
        start, end = res.span()
        groups = []
        groups.append(haystack[:start])
        groups.append("[red]")
        groups.append(haystack[start:end])
        groups.append("[/red]")
        groups.append(haystack[end:])

        return "".join(groups)

def main():
    show_fnames = False
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

    # Whether or not to print the filename
    parser.add_argument(
        "-H",
        "--filename",
        dest="show_filename",
        choices=ShowFilename,
        metavar="WHEN",
        help=f"Show the filename for each matching line; WHEN is [{', '.join(ShowFilename)}]",
    )

    # Whether or not to show the document number
    parser.add_argument(
        "-D",
        "--doc-number",
        dest="show_doc_number",
        choices=ShowDocumentNumber,
        metavar="WHEN",
        help=f"Show the number of the yaml document in multi-document files; WHEN is [{', '.join(ShowDocumentNumber)}]",
    )

    parser.add_argument(
        "-c",
        "--color",
        "--colour",
        dest="use_color",
        choices=UseColour,
        metavar="WHEN",
        help=f"Whether or not to use colour to highlight matches; WHEN is [{', '.join(UseColour)}]",
    )

    parser.add_argument("pattern", help="The pattern to search for")
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
            if len(args.input_files) > 1:
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

    try:
        for filename, file_obj in iter_files(args.input_files):
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
                for path, val in handle_obj(document):
                    res = matcher(args.pattern, str(val))
                    if res:
                        if doc_was_matched and not doc_matched:
                            console.print("---")
                        doc_matched = True
                        console.print(f"{prefix}[blue]{path}[/blue] {res}")
            if is_tty:
                print()

    except KeyboardInterrupt:
        return


if __name__ == "__main__":
    main()
