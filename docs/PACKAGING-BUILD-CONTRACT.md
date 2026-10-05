---
document_role: contract
freshness_policy: living
document_living_note: >-
  Describes the packaging build and the members an install requires, both of
  which change when the project layout changes. Living: the required-member list
  is a claim about the artifacts, so it is re-derived by
  `tests/unit/test_build_package.py` on every run rather than trusted here.
---

# Packaging Build Contract

## 1. What this covers

`python -m build` reports success for artifacts that are missing things. A wheel
without the IDE page, a wheel without a licence file and a wheel whose console
scripts do not exist all exit zero, because none of them is a build error. They
are packaging decisions that nobody looked at.

This contract covers the build entry point, `scripts/build_package.py`, which
builds the distributions and then opens the artifacts and checks their members.

## 2. Required members

Checked by the script, in the artifact as produced.

| Artifact | Required |
| --- | --- |
| wheel | `rdebug_ide/static/index.html` |
| wheel | `rdebug_ide/app.py`, `rdebug/cli.py`, `rdebug_mcp/server.py` |
| wheel | a `LICENSE` entry under `dist-info/licenses` |
| wheel | `entry_points.txt` declaring `rdebug`, `rdebug-mcp`, `rdebug-ide` |
| sdist | `pyproject.toml`, `LICENSE`, `README.md` |
| sdist | `src/rdebug_ide/static/index.html` |

`rdebug_ide/static/index.html` is the one that matters most. Without it `pip`
succeeds, `rdebug-ide` starts, and it serves no page.

## 3. Two declarations the artifacts depend on

`[tool.setuptools.package-data]` with `rdebug_ide = ["static/*.html"]`, and the
absence of a `License ::` classifier.

Both were wrong in this repository at the time this contract was written, and no
test noticed either, because nothing built a package.

- PEP 639 supersedes the `License ::` classifier with the `license` expression and
  `license-files`. With both present, setuptools 78 refuses to build at all.
- setuptools does not collect `.html` on its own without `MANIFEST.in` or a VCS
  plugin, and this repository has neither, so the asset has to be declared.

`tests/unit/test_build_package.py` pins both declarations directly, so a
regression is caught without spending a build.

## 4. The build runs against a staged copy

setuptools caches the file manifest in `src/*.egg-info/SOURCES.txt` and reuses
`build/lib`. Building in place therefore inherits state from earlier builds.

This was measured, not assumed: with the `package-data` section deleted, the wheel
still contained `index.html` and the check passed, because a previous build had
left the manifest entry behind.

`scripts/build_package.py` copies the declared inputs into a clean directory and
builds there. The input list is explicit rather than globbed, so "what goes into
a release" is readable in one place and build state cannot leak into an artifact.

## 5. Exit codes

| Code | Meaning |
| --- | --- |
| 0 | both artifacts built and contain every required member |
| 2 | **REGRESSION**: the build succeeded and an artifact is incomplete |
| 3 | **INFRASTRUCTURE**: the backend is absent, the build would not run, or an artifact is unreadable |

A missing `build` backend is exit 3, never a skip and never a pass. "The machine
could not answer" and "the answer is no" must not share a code.

## 6. CI

The `package-build` job in `.github/workflows/ci.yml`. It is a separate job from
`section4-gates` on purpose: the gates cannot pass on a hosted runner, so folding
packaging into them would make a real packaging failure indistinguishable from
the infrastructure failure already expected there.

A green `package-build` means the artifacts are complete and installable. It says
nothing about the replay gates, and it is not release blocking.

## 7. What this does not establish

| Item | Status |
| --- | --- |
| An install of the wheel was exercised end to end | **NOT ESTABLISHED** — the archive members are inspected, not installed and run |
| The sdist builds on a clean machine with no `build` backend present | **NOT ESTABLISHED** — CI installs the backend first |
| The artifacts install on Windows, macOS and Linux | **NOT ESTABLISHED** — the wheel is `py3-none-any`, but no platform matrix runs |
| Release blocking | **NOT AUTHORIZED**, consistent with `CI-ORCHESTRATION-CONTRACT.md` |