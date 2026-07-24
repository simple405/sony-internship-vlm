# Write Documented Code

When invoked, apply these documentation rules to **all** code written in this session.

## Before Writing Any Code

Confirm:
- What does this module/function/class do? (→ module + function docstrings)
- What are the non-obvious design choices? (→ inline comments explaining WHY)
- Are there magic numbers or thresholds? (→ named constants with comments)

## Documentation Checklist (apply to every file)

### 1. Module docstring
Every `.py` file starts with a docstring:
```python
"""Short summary (one line).

Extended description: what pipeline stage this belongs to, key I/O,
environment requirements (GPU, conda env, API keys).

Usage:
    python -m vlm.scripts.foo --arg value
"""
```

### 2. Function/method docstrings — Google style
```python
def fn(param: type, opt: float = 0.5) -> ReturnType:
    """One-line summary.

    Args:
        param: What this represents and valid range.
        opt: Optional threshold (0.0–1.0).

    Returns:
        Description of the return value and its structure.

    Raises:
        ValueError: When param is invalid.
    """
```

### 3. Inline comments — explain the WHY
```python
# Inverse depth: closer objects get larger values, matching DA3 convention
inverse = 1.0 / depth

BATCH_SIZE = 10  # DashScope text-embedding-v3 rejects batches > 10
```

### 4. Section banners for long files
```python
# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------
```

## Quality Gate Before Marking Task Done

- [ ] Every function has a docstring
- [ ] Module has a docstring
- [ ] Magic numbers are explained
- [ ] Non-obvious algorithms have inline comments
- [ ] No comment just restates the code name

## Verification Command

```powershell
.venv\Scripts\pydocstyle.exe vlm/scripts/ --convention=google --add-ignore=D100,D104
```

Any output = missing docstrings that need to be added.
