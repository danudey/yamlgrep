# yamlgrep

A simple-ish program to "grep" for values in a yaml file

`yamlgrep` works by taking a series of yaml files and traversing the entire tree; when it finds a value which matches the pattern given, it prints the filename (optional), the number of the document within that file (optional), the path to the value.

Example:

```
$ yamlgrep foo thismanifest.yaml thatmanifest.yaml
thismanifest.yaml:1: .spec.containers.0.image foo.io/eieio/myimg:v1.31.1
thatmanifest.yaml:8: .spec.containers.0.image foo.io/eieio/myimg:v1.32.4
```

## Matching keys

By default only values are searched. Pass `-k` to match key names as well, or `--match keys` to match key names only:

```
$ yamlgrep -k name thismanifest.yaml
.metadata.name my-deployment
.spec.containers.0.name myimg

$ yamlgrep --match keys labels thismanifest.yaml
.metadata.labels.app myapp
.metadata.labels.tier web
```

A key matches if *any* key in the path to a value matches the pattern, so `--match keys labels` shows everything underneath any `labels` key. To match only the last key in the path instead, pass `--last-key` (which implies `-k` unless you also pass `--match`):

```
$ yamlgrep --last-key name thismanifest.yaml
.metadata.name my-deployment
.spec.containers.0.name myimg
```

With `--last-key`, the pattern `metadata` no longer matches `.metadata.name`, since `metadata` isn't the last key in that path.

When a key matched by `--last-key` holds a mapping or a list, the whole subtree underneath it is printed once, as an indented yaml block, instead of once per value inside it:

```
$ yamlgrep --last-key labels thismanifest.yaml
.metadata.labels:
    app: myapp
    tier: web
```

The `--help` is pretty good in explaining things.

## Requirements

`yamlgrep` currently requires Python 3.12, but only because Python 3.12 handles some things a little nicer. I'll be adding support for earlier Python versions soon. If I haven't done so yet, [thumbs-up this issue](https://github.com/danudey/yamlgrep/issues/11) and that'll nudge me to doing it.

## Installation

You should probably use a tool like `uv` or `pipx` to install; this will create a virtualenv for the tool and maintain it as needed, which avoids changing, installing, or removing packages from your global Python installation.

### Installing via `uv` (recommended)

If you have the `uv` tool [installed](https://docs.astral.sh/uv/#installation), you can simply run:

```sh
uv tool install -U yamlgrep
```

This will install `yamlgrep`, or upgrade it if it's already installed.

### Installing via `pipx`

Similarly, if you have [`pipx`](https://github.com/pypa/pipx) installed, run:

```sh
pipx install yamlgrep
```

And to upgrade:

```sh
pipx upgrade yamlgrep
```

### Installing via `pip` (not recommended)

On some newer systems (e.g. Ubuntu 23.10 and later), installing packages via `pip install` is not supported outside of a virtualenv, so we recommend using one of the above tools. If you don't want to, then you can install yamlgrep via `pip` as you would any other tool.