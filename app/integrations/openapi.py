from typing import Any

HTTP_METHODS = {"get", "post", "put", "patch", "delete"}


def _schema_from_operation(operation: dict[str, Any]) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    required: list[str] = []
    for parameter in operation.get("parameters") or []:
        if parameter.get("in") not in {"query", "path"}:
            continue
        name = parameter.get("name")
        if not name:
            continue
        schema = parameter.get("schema") or {"type": "string"}
        properties[name] = schema
        if parameter.get("required"):
            required.append(name)
    request_body = operation.get("requestBody") or {}
    content = (request_body.get("content") or {}).get("application/json") or {}
    body_schema = content.get("schema") or {}
    if body_schema.get("properties"):
        properties.update(body_schema["properties"])
        required.extend(body_schema.get("required") or [])
    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = sorted(set(required))
    return schema


def parse_openapi(spec: dict[str, Any]) -> list[dict[str, Any]]:
    """从 OpenAPI 3 文档生成工具定义候选。"""
    tools: list[dict[str, Any]] = []
    for path, operations in (spec.get("paths") or {}).items():
        for method, operation in operations.items():
            if method.lower() not in HTTP_METHODS or not isinstance(operation, dict):
                continue
            tool_code = operation.get("operationId") or f"{method.lower()}.{path.strip('/').replace('/', '.')}"
            tools.append(
                {
                    "tool_code": tool_code,
                    "name": operation.get("summary") or tool_code,
                    "description": operation.get("description"),
                    "source_type": "OPENAPI",
                    "endpoint": path,
                    "method": method.lower(),
                    "input_schema": _schema_from_operation(operation),
                    "write_operation": method.lower() in {"post", "put", "patch", "delete"},
                }
            )
    return tools
