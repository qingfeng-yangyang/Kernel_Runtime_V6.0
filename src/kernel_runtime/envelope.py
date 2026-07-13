from __future__ import annotations

import json
from typing import Any

from .errors import ValidationFailure
from .models import ModuleResult
from .security import reject_secrets, reject_unsafe_markup


class EnvelopeValidator:
    TOP = {"stage", "module", "output", "log_content"}
    LOG = {"status", "event", "error_code", "error_message"}

    def validate_raw(self, raw: str | dict[str, Any], *, stage: str, module: str,
                     allowed_output_fields: tuple[str, ...]) -> ModuleResult:
        if isinstance(raw, str):
            decoder = json.JSONDecoder()
            try:
                parsed, end = decoder.raw_decode(raw)
            except json.JSONDecodeError as exc:
                raise ValidationFailure("INVALID_JSON", "Module output is not valid JSON") from exc
            if raw[end:].strip():
                raise ValidationFailure("JSON_TRAILING_TEXT", "Text outside JSON is forbidden")
        else:
            parsed = raw
        if not isinstance(parsed, dict) or set(parsed) != self.TOP:
            raise ValidationFailure("INVALID_ENVELOPE", "Envelope fields must match exactly")
        if parsed["stage"] != stage:
            raise ValidationFailure("STAGE_MISMATCH", "Envelope stage mismatch")
        if parsed["module"] != module:
            raise ValidationFailure("MODULE_MISMATCH", "Envelope module mismatch")
        output, log = parsed["output"], parsed["log_content"]
        if not isinstance(output, dict) or set(output) != set(allowed_output_fields):
            raise ValidationFailure("INVALID_OUTPUT_FIELDS", "Output fields do not match stage contract")
        if not isinstance(log, dict) or set(log) != self.LOG:
            raise ValidationFailure("INVALID_LOG_CONTENT", "log_content fields must match exactly")
        if log["status"] not in {"success", "failed"}:
            raise ValidationFailure("INVALID_LOG_STATUS", "Invalid log status")
        reject_secrets(parsed)
        reject_unsafe_markup(parsed)
        return ModuleResult(output, log["event"], log["status"], log["error_code"], log["error_message"])

