from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class PromptPackage:
    prompt_id: str
    version: str
    application_id: str
    module_id: str
    static_prompt: str
    checksum: str

    @classmethod
    def load(cls, directory: str | Path, *, prompt_id: str, version: str,
             application_id: str, module_id: str) -> "PromptPackage":
        root = Path(directory)
        parts = [(root / name).read_text(encoding="utf-8").strip()
                 for name in ("identity.txt", "base.txt", "corrections.txt")]
        compiled = "\n\n".join(parts) + "\n"
        checksum = hashlib.sha256(compiled.encode("utf-8")).hexdigest()
        return cls(prompt_id, version, application_id, module_id, compiled, checksum)

    @classmethod
    def load_compiled(cls, file: str | Path, *, prompt_id: str, version: str,
                      application_id: str, module_id: str) -> "PromptPackage":
        compiled = Path(file).read_text(encoding="utf-8").strip() + "\n"
        compiled = compiled.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
        if not compiled.strip() or "电商客服" not in compiled:
            raise ValueError(f"Prompt package is incomplete: {file}")
        checksum = hashlib.sha256(compiled.encode("utf-8")).hexdigest()
        return cls(prompt_id, version, application_id, module_id, compiled, checksum)

    def messages(self, dynamic_context: dict[str, Any], task_input: str) -> list[dict[str, str]]:
        return [
            {"role": "system", "content": self.static_prompt},
            {"role": "user", "content": "RUNTIME_DYNAMIC_CONTEXT_JSON\n" +
             json.dumps(dynamic_context, ensure_ascii=False, separators=(",", ":"))},
            {"role": "user", "content": "CURRENT_TASK_INPUT_JSON\n" +
             json.dumps({"task_input": task_input}, ensure_ascii=False, separators=(",", ":"))},
        ]
