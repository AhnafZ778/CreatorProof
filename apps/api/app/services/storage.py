from pathlib import Path


class LocalObjectStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def put(self, key: str, raw: bytes) -> str:
        safe = Path(key)
        if safe.is_absolute() or ".." in safe.parts:
            raise ValueError("Unsafe storage key")
        target = (self.root / safe).resolve()
        if self.root not in target.parents:
            raise ValueError("Unsafe storage key")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        return str(safe)

    def read(self, key: str) -> bytes:
        target = (self.root / key).resolve()
        if self.root not in target.parents:
            raise ValueError("Unsafe storage key")
        return target.read_bytes()

    def delete(self, key: str | None) -> None:
        if not key:
            return
        target = (self.root / key).resolve()
        if self.root not in target.parents:
            raise ValueError("Unsafe storage key")
        target.unlink(missing_ok=True)
