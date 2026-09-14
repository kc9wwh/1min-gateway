# onemin-gateway (Python package)

See the [repo root README](../README.md) for the full picture. This
directory is the installable Python half of the project.

```
pip install -e .[dev]        # editable install with test deps
1min-gateway                 # run the server (reads ~/.config/1min-gateway/config.json)
pytest                        # run the test suite
```

Config is not created by `pip install` -- the first run of `1min-gateway`
(or the OpenCode plugin's installer) writes a default `config.json` to the
cross-platform config directory. Copy values from `config.sample.json` and
fill in your API key, or edit the generated file directly.
