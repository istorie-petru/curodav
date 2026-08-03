"""Pure LWW arbitration (ARCHITECTURE.md §7.4-7.5).

Ported from server/app/lww.py. HLCs are fixed-width sortable strings:
string comparison IS causal comparison.
"""


def wins(op_hlc: str, stored_hlc: str | None) -> bool:
    """True if an op with *op_hlc* beats the stored high-water mark."""
    return stored_hlc is None or op_hlc > stored_hlc


def merge_hlc(local: str | None, remote: str) -> str:
    """New high-water mark after observing a remote stamp."""
    if local is None or remote > local:
        return remote
    return local
