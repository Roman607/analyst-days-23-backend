from pathlib import Path

import yaml

from app.main import app

CONTRACT = Path(__file__).resolve().parents[1] / "API/openapi.yaml"


def dereference(document, value):
    if isinstance(value, dict):
        if "$ref" in value:
            pointer = value["$ref"]
            assert pointer.startswith("#/")
            target = document
            for part in pointer[2:].split("/"):
                target = target[part.replace("~1", "/").replace("~0", "~")]
            return dereference(document, target)
        return {key: dereference(document, item) for key, item in value.items()}
    if isinstance(value, list):
        return [dereference(document, item) for item in value]
    return value


def schema_shape(schema):
    if "allOf" in schema:
        base, restriction = schema["allOf"]
        properties = base["properties"]
        schema = {**base, "properties": {
            **properties,
            **{key: {**properties[key], **value} for key, value in restriction["properties"].items()},
        }}

    shape = {}
    if "const" in schema:
        value = schema["const"]
        return {"const": value, "type": "array" if isinstance(value, list) else "string"}
    if "enum" in schema:
        values = sorted(schema["enum"])
        return {"const": values[0], "type": "string"} if len(values) == 1 else {
            "enum": values, "type": schema.get("type", "string"),
        }
    if "anyOf" in schema:
        return {"type": sorted(item["type"] for item in schema["anyOf"])}
    for key in ("type", "additionalProperties", "minLength", "pattern", "uniqueItems"):
        if key in schema:
            value = schema[key]
            shape[key] = sorted(value) if isinstance(value, list) else value
    if "required" in schema:
        shape["required"] = sorted(schema["required"])
    if "items" in schema:
        shape["items"] = schema_shape(schema["items"])
    if "properties" in schema:
        shape["properties"] = {name: schema_shape(value) for name, value in schema["properties"].items()}
    return shape


def content_shape(content):
    return {media: schema_shape(value["schema"]) for media, value in content.items()}


def operation_shape(operation):
    request = operation.get("requestBody", {})
    return {
        "operationId": operation["operationId"],
        "request_required": request.get("required", False),
        "request_content": content_shape(request.get("content", {})),
        "responses": {
            status: {
                "content": content_shape(response.get("content", {})),
                "headers": {name.lower(): schema_shape(value["schema"])
                            for name, value in response.get("headers", {}).items()},
            }
            for status, response in operation["responses"].items()
        },
    }


def contract_shape(document):
    assert document["openapi"].startswith("3.1.")
    return {
        path: {method: operation_shape(operation) for method, operation in methods.items()}
        for path, methods in dereference(document, document["paths"]).items()
    }


def test_generated_openapi_matches_contract():
    assert contract_shape(app.openapi()) == contract_shape(yaml.safe_load(CONTRACT.read_text(encoding="utf-8")))
