# yamlgrep

A simple-ish program to "grep" for values in a yaml file

`yamlgrep` works by taking a series of yaml files and traversing the entire tree; when it finds a value which matches the pattern given, it prints the filename (optional), the number of the document within that file (optional), the path to the value.

Example:

```
$ yamlgrep foo thismanifest.yaml thatmanifest.yaml
thismanifest.yaml:1: .spec.containers.0.image foo.io/eieio/myimg:v1.31.1
thatmanifest.yaml:8: .spec.containers.0.image foo.io/eieio/myimg:v1.32.4
```

The `--help` is pretty good in explaining things.