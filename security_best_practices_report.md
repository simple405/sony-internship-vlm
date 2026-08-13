# Security Risk Maintenance Report

Date: 2026-08-12
Workspace: `D:\索尼实习`
Scope: Python VLM batch pipeline risks identified in the CKPT-10 security review.
Data constraint: existing artifacts under `vlm/data/` must not be deleted; temporary staging files may be deleted.

## Executive summary

The three medium operational risks from the original review are now **remediated**. Existing smoke datasets, SN7 packages, paired-review bundles, and human-gold packages are no longer hard-deleted during overwrite publication. They are moved into unique versioned archive directories before the new staged output is published.

The current residual risk is **low**. Archives are intentionally not auto-pruned, so repeated overwrites consume additional disk space. Archive retention should remain a deliberate operator action because automatic cleanup would conflict with the data-preservation requirement.

No existing file under `vlm/data/` was deleted, moved, renamed, or content-modified while implementing or testing this maintenance.

## Maintenance changes

### M-01: SN7 smoke overwrite hard-deleted the existing output

**Status: Remediated**

- `vlm/scripts/prepare_sn7_smoke_test.py:80` still refuses an existing output unless `--overwrite` is explicit.
- `vlm/scripts/prepare_sn7_smoke_test.py:86` builds the replacement in a temporary staging directory.
- `vlm/scripts/prepare_sn7_smoke_test.py:152` publishes through the preservation helper instead of calling `shutil.rmtree()` on the existing data root.
- Failed or unpublished staging directories may still be removed at `vlm/scripts/prepare_sn7_smoke_test.py:161`; these are disposable temporary files, not prior data artifacts.

### M-02: Package and review publication deleted the previous directory

**Status: Remediated**

- `vlm/scripts/package_sn7_dataset.py:274` now archives the current package before staged publication.
- `vlm/scripts/supervise/sync_paired_front_view_review.py:95` archives each previous sample review directory. Older machine-review evidence is retained in the archive instead of being unlinked.
- `vlm/scripts/supervise/sync_paired_front_view_review.py:275` applies the same behavior to the central review bundle.
- The old `.previous` directory plus post-success `shutil.rmtree()` pattern has been removed.

### M-03: Human-gold overwrite could replace manual annotations

**Status: Remediated**

- Default behavior still refuses overwrite of possible manual annotations at `vlm/scripts/supervise/prepare_paired_front_view_human_gold.py:456`.
- With explicit `--overwrite`, the complete current package is archived at `vlm/scripts/supervise/prepare_paired_front_view_human_gold.py:498` before the replacement is published.
- A previous `validation_summary.json` is preserved with its package instead of being deleted.

## Shared guardrail

`vlm/scripts/_preservation.py` provides the common publication primitive:

- `archive_existing_path()` moves the old path to a unique UTC timestamp plus random-suffix archive at line 30.
- `publish_staged_directory()` publishes the staged directory and restores the archived version if final publication fails at line 51.
- The helper refuses to archive the protected root itself, preventing accidental movement of all `vlm/data`.

Archive layout:

```text
# Destination below vlm/data
vlm/data/_archive/<original-relative-path>/<utc-timestamp>-<suffix>/

# Destination outside vlm/data, such as vlm/tmp human-gold output
<destination-parent>/_archive/<destination-name>/<utc-timestamp>-<suffix>/
```

No automatic archive deletion was added.

## Verification

- Targeted preservation/security/workflow suite: **40 passed**.
- Full test suite: **112 passed**.
- Script compilation: `python -m compileall -q vlm\scripts` -> passed.
- Diff whitespace check: `git diff --check` -> passed; only existing line-ending warnings were reported.
- `git status --short -- vlm/data vlm/tmp` -> no data or temp-tree changes.

New regression coverage in `tests/test_data_preservation.py` verifies:

- existing paths are archived rather than deleted;
- the protected data root cannot be archived;
- failed publication restores the previous destination;
- smoke overwrite preserves its previous dataset;
- package overwrite preserves its previous deliverable;
- sample and central review sync preserve previous review evidence;
- human-gold overwrite preserves manual annotations.

## Remaining operational note

Archive growth is expected and intentional. Disk usage can be monitored, but any future retention or pruning command must require an explicit archive target and must not treat `vlm/data/_archive` as disposable temporary storage.
