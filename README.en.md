# mathematica-skill

**Let an agent actually drive Mathematica — not draw a picture that looks like the answer.**

A local-first automation system for Mathematica / Wolfram Language: one shared engine behind a CLI, an MCP
server and an Agent Skill. It takes a task description, produces native Wolfram computation, a real
`.nb`, native PNG/PDF figures and data files, then proves the result by recomputing it in a clean kernel.

```
intake → inspect → plan → lint → preflight → native_build → native_evaluate
      → export → close → reopen → rerun → compare → review → deliver
```

![mathematica-skill](assets/icon.svg)

---

## 1. Why this exists

Most "AI for Mathematica" tools stop at code snippets or a look-alike image:

- the `.nb` opens as plain text with no executable cells;
- a Python-drawn PNG is pasted in and presented as Wolfram output;
- the tool says "verified" without ever running the kernel;
- the notebook breaks on another machine because paths were absolute;
- the delivery folder is full of `.py`, `.json`, logs and screenshots.

This project exists to close each of those holes.

## 2. Design principles

### 2.1 Real computation, no substitutes

Every mathematical result comes from a licensed Wolfram kernel: `Integrate`, `DSolve`, `NDSolve`,
`NMinimize`, `LinearModelFit`, `RandomVariate`, … Figures come from `Plot`, `ListLinePlot`,
`ParametricPlot3D`, `Graphics3D`, exported through `Rasterize` and `Export`.

Python does exactly four things: launch processes, copy files, inspect artifacts, compare numbers.
It never performs the mathematics and never redraws the final figure.

### 2.2 The notebook must be real

The `.nb` is produced by Mathematica's own parser and exporter and executed by a real front end:

```
NotebookOpen → NotebookEvaluate[InsertResults → True] → NotebookSave → NotebookClose → reopen
```

Code cells keep the original source text, so comments, indentation and blank lines survive; they are not
text cells pretending to be code.

### 2.3 No evidence, no "verified"

`verified` has exactly one path:

1. the kernel really evaluates every check;
2. the front end really opens, evaluates, saves and reopens the notebook;
3. a fresh process recomputes and matches item by item;
4. PNG dimensions are exact, the image is not blank and the file is intact;
5. the delivery folder contains only whitelisted files.

Miss one and the run is `draft` or `blocked`, and the report says which gate failed.

### 2.4 Internal work stays apart from delivery

```
work/<run>/                 ← internal: task copy, logs, two-run comparison, reports
└── deliver/<name>/         ← client: .nb + optional .wl + PNG/PDF/CSV/XLSX
```

Internal directories never reach the client; client folders never contain Python, JSON, logs or screenshots.

### 2.5 Cross-platform, honestly

macOS on Apple Silicon is the primary acceptance platform. Windows and Linux paths, processes and encoding
are adapted, but a platform only counts as verified when a real run has happened there. See
[COMPATIBILITY.md](COMPATIBILITY.md).

## 3. What you get

| Area | Behaviour |
| --- | --- |
| Task parsing | Structured `task.json` from prose, old notebooks, CSV or recognised images |
| Code quality | Lexical bracket/string/comment check plus a policy scan that blocks risky calls by default |
| Native compute | Real kernel run; captures `$Failed`, messages, aborts, timeouts |
| Notebook | Real Input cells, real Output, reopenable and recomputable |
| Notebook editing | `edit` replaces/inserts/appends cells by index, leaving everything else intact; text is verified after writing, so no mojibake |
| Language following | `language: "auto"` writes English for English material, Chinese for Chinese, including CJK plot fonts, decided from prompts and from `\:xxxx`-escaped text in source notebooks |
| Figures | 1600×900 / 4K / A4@300dpi presets, aspect preserved with white padding, never stretched |
| Data | Native `Export` to CSV/XLSX/JSON with a read-back check |
| Reproduction | Two independent processes, per-check numeric/symbolic comparison with per-task tolerances |
| Figure QA | Read-only dimensions, blankness, colour and integrity checks |
| Reporting | `validation.json` + `VALIDATION.md`, including an explicit verification-boundary section |
| Delivery | Whitelisted folder plus a SHA-256 manifest |
| Installer | `install / update / rollback / uninstall`, only touching files it created |
| MCP | Nine `mathematica_*` tools over stdio, newline-delimited JSON |
| Skill | Agent Skills frontmatter; installs into Claude, Codex, Cursor, OpenCode, … |

## 4. Install (three channels, usable immediately)

```bash
npx mathematica-skill doctor --frontend     # no install
npm i -g mathematica-skill                  # global install
pip install mathematica-skill               # Python install
```

All three run the same orchestration layer, the same Wolfram scripts and the same skill.
The npm tarball already ships the Python source and `wolfram/`, so no second `pip install` is needed.
See [docs/INSTALL.md](docs/INSTALL.md).


`doctor` answers three questions: is there a kernel, is the licence usable, is there a notebook front end.

```bash
mathematica-skill example --write task.json
mathematica-skill plan task.json
mathematica-skill run  task.json --out work --seed 20261031
```

Output:

```
work/<run>/deliver/<name>/
├── sine-and-its-integral.nb     # real notebook with evaluated outputs
└── sine.png                     # native 1600×900 export
```

On a machine without Mathematica:

```bash
mathematica-skill run task.json --allow-draft   # draft only, verified stays false
mathematica-skill build task.json --draft --out build/
```

## 5. Task format

```json
{
  "schema_version": "1.0",
  "title": "Logistic map and Lyapunov exponent",
  "language": "en",
  "seed": 20261031,
  "assumptions": ["r = 4 is fully chaotic", "first 1000 iterates discarded"],
  "sources": ["data/series.csv"],
  "tasks": [
    {
      "id": "logistic",
      "prompt": "Compute the Lyapunov exponent for r = 4 and plot the orbit.",
      "code": "orbit = NestList[4. # (1 - #) &, 0.123456, 5000];\nlyap = Mean[Log[Abs[4. (1 - 2 Most[orbit])]]];\nfig = ListLinePlot[orbit[[1 ;; 300]], Frame -> True];",
      "checks": [
        {"id": "lyap_value", "kind": "numeric", "expression": "lyap", "expected": 0.6931, "abs_tol": 0.01},
        {"id": "orbit_length", "kind": "numeric", "expression": "Length[orbit]", "expected": 5001}
      ]
    }
  ],
  "outputs": [
    {"id": "orbit_fig", "task": "logistic", "kind": "figure", "filename": "orbit.png",
     "expression": "fig", "width": 3840, "height": 2160, "dpi": 300, "title": "Logistic orbit"}
  ],
  "delivery": {"name": "logistic-delivery", "include": ["orbit_fig"]},
  "metadata": {"deliver_code": false}
}
```

Rules:

- `code` must be runnable Wolfram Language, never pseudocode.
- `checks` must carry a comparable `expected` and a tolerance; no checks means nothing is verified.
- `outputs[].expression` must have been computed by the code above.
- `sources` are relative paths, copied into an isolated run directory.
- `delivery.include` selects which outputs reach the client folder.

## 6. Commands

| Command | Purpose |
| --- | --- |
| `doctor` | Kernel / licence / front end / AgentTools probe, `--json` supported |
| `plan` | Parse a task and print the plan without starting a kernel |
| `lint` | Lexical and policy checks |
| `run` | Full pipeline; either a verified delivery or an explicit failure state |
| `build` | Only produce `.nb` and `.wl` (`--draft` needs no Mathematica) |
| `evaluate` | Run an existing `.nb` in the front end |
| `export` | Export figures and data from real expressions |
| `verify` | Evaluate checks in a clean kernel, optionally compare with a previous run |
| `install` / `update` / `uninstall` / `rollback` | Skill and MCP configuration, `--dry-run` supported |
| `example` | Print a runnable task JSON |
| `edit` | Edit an existing `.nb`: replace/insert/append/delete cells, retitle, flip heading language |
| `mcp serve` | Start the MCP stdio server |

## 7. MCP tools

```
mathematica_doctor            mathematica_plan             mathematica_lint
mathematica_build             mathematica_run              mathematica_evaluate_notebook
mathematica_export            mathematica_verify           mathematica_example
mathematica_edit_notebook
```

Every tool returns structured JSON text; internal errors are JSON too, with `isError: true`. The
`mathematica_` prefix avoids collisions with the official Wolfram MCP server.

```bash
mathematica-skill install --mcp-client claude
mathematica-skill install --mcp-client codex
mathematica-skill install --mcp-client opencode
mathematica-skill install --mcp-client cursor --config ~/.cursor/mcp.json
```

The installer merges a single key and never overwrites other servers; if the key exists it asks for
`--force` instead of silently replacing it.

## 8. Layout

```
mathematica-skill/
├── mathematica_skill/        # Python orchestration (I/O, processes, gates only)
├── wolfram/                  # native side: build/evaluate/export/verify, methods, plot theme
├── skills/mathematica-native # Agent Skill: SKILL.md + references
├── examples/                 # runnable tasks, including deliberately failing ones
├── tests/                    # unit / integration / regression
├── docs/                     # architecture, CLI, validation, security, macOS
└── .github/workflows/        # lint and tests
```

## 9. Verification boundary

| Environment | What it can prove |
| --- | --- |
| No Mathematica | Draft only; `verified` stays false |
| Kernel, no front end | `.wl` runs, figures export, checks compare; the `.nb` **cannot** be verified |
| Kernel and front end | Full pipeline, still subject to the independent re-run |
| Only tested on Linux | Cannot claim macOS or Windows verification |

A reviewer only needs two things: `findings` in `_validation/validation.json`, and
`frontend_used / output_cells / failed_outputs` in the `native` section.

## 10. Security

- Task code is untrusted: `Run`, `RunProcess`, `URL*`, host-absolute paths and `LibraryLoad` are blocked by default.
- `--allow-external` downgrades a block to a warning and records it; nothing is silently allowed.
- Nothing is uploaded: tasks, data and notebooks stay local.
- Activation data is never bundled, shared or bypassed; an unusable licence is a stop condition.

Details: `skills/mathematica-native/references/security.md`.

## 11. Development

```bash
python3 -m pip install -e .
python3 -m pytest -q          # unit tests, no Mathematica required
python3 scripts/check.py      # lexical checks + WL bracket balance + tests
```

Tests that need a real kernel are marked `@pytest.mark.native`; public CI skips them and never fakes a pass.

## 12. Licence

MIT, see [LICENSE](LICENSE). Mathematica itself is commercial software; this project does not contain,
modify or circumvent its licensing.

---

**中文**: [README.md](README.md)
