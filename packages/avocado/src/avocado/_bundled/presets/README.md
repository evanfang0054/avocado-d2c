# Component library presets

Built-in YAML presets that map Figma node names → business components.
Loaded via the CLI flag `--component-lib <name>`.

## Available presets

| Name | Library |
| --- | --- |
| `antd` | Ant Design (open-source example preset) |

## Usage

```bash
# Load preset by name
avocado URL --component-lib antd -o out.jsx

# Combine with layout mode (the two options are orthogonal)
avocado URL --layout flex     --component-lib antd -o out.jsx
avocado URL --layout absolute --component-lib antd -o out.jsx
```

`--component-lib` and `--components <file>` are mutually exclusive.
`--components` (a custom YAML file) takes precedence when both are given
— the CLI exits with code 2 if both are passed.

## Writing a preset for a new component library

1. Create `presets/<libname>.yaml` next to this README.
2. Add one entry per component using this shape:

   ```yaml
   components:
     # Match by Figma layer name (case-insensitive, exact)
     - name: "Button"
       component: "Button"            # PascalCase export name
       package: "@your-org/your-lib"
       props:                          # optional preset props
         theme: "border"

     # Common designer naming variants can map to the same component
     - name: "btn"
       component: "Button"
       package: "@your-org/your-lib"

     # componentId match — most precise, survives renames.
     # Fill in with real ids from your Figma file.
     - componentId: "1454:7935"
       component: "Button"
       package: "@your-org/your-lib"
   ```

3. Use it: `avocado URL --component-lib <libname>`.

## Matching precedence

When multiple entries match a node:

1. **componentId match** (highest confidence, INSTANCE only)
2. **exact name match** (case-insensitive)

## Recognition scope

By default avocado only matches `INSTANCE` nodes (per the project design docs — Figma REST
API does not expose `sharedPluginData`, so non-INSTANCE identification
would be heuristic). For structural recognition of plain FRAME/RECTANGLE/
TEXT layers, write a plugin that hooks `modify_json_schema` — see
`docs/preset-guide.md` for how to write and install user plugins.
