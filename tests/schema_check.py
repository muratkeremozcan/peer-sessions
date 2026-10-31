"""A small JSON Schema subset validator, so tests need no third-party package.

Supports the keywords schemas/launch-receipt.v1.schema.json uses: type,
required, properties, additionalProperties, items, enum, const, minLength.
"""

import json
import os

from helpers import ROOT

SCHEMA_PATH = os.path.join(ROOT, "schemas", "launch-receipt.v1.schema.json")
TYPES = {
    "object": dict,
    "array": list,
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "null": type(None),
}


def load_schema():
    with open(SCHEMA_PATH) as handle:
        return json.load(handle)


def _is(value, name):
    if name in ("integer", "number") and isinstance(value, bool):
        return False
    return isinstance(value, TYPES[name])


def errors(value, schema, where="$"):
    found = []
    expected = schema.get("type")
    if expected is not None:
        names = expected if isinstance(expected, list) else [expected]
        if not any(_is(value, name) for name in names):
            return [f"{where}: expected {expected}, got {type(value).__name__}"]
    if "const" in schema and value != schema["const"]:
        found.append(f"{where}: expected {schema['const']!r}, got {value!r}")
    if "enum" in schema and value not in schema["enum"]:
        found.append(f"{where}: {value!r} not in {schema['enum']}")
    if isinstance(value, str) and len(value) < schema.get("minLength", 0):
        found.append(f"{where}: shorter than {schema['minLength']}")
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                found.append(f"{where}: missing {key}")
        properties = schema.get("properties", {})
        extra = schema.get("additionalProperties")
        for key, item in value.items():
            if key in properties:
                found += errors(item, properties[key], f"{where}.{key}")
            elif isinstance(extra, dict):
                found += errors(item, extra, f"{where}.{key}")
    if isinstance(value, list) and "items" in schema:
        for index, item in enumerate(value):
            found += errors(item, schema["items"], f"{where}[{index}]")
    return found
