# opencode-1min-gateway (plugin)

See the [repo root README](../README.md) for the full picture. This
directory is the OpenCode plugin half of the project.

```
npm install
npm run build     # compiles src/ -> dist/
```

## Local install into OpenCode

Point OpenCode at this plugin by path in your project or global
`opencode.json`:

```json
{
  "plugin": ["file:///C:/Users/Knott/dev/1min-gateway/plugin"]
}
```

(or the OS-appropriate equivalent path). On OpenCode's next start, the
plugin bootstraps and starts the gateway, then registers the `1min-gateway`
provider automatically -- no separate "install" step needed.
