#!/usr/bin/env python3
"""Inspect ONNX identity, tensor contracts, and possible input preprocessing."""

import argparse
import hashlib
import json
import sys
from collections import Counter, deque
from pathlib import Path


PREPROCESSING_OPS = {
    "Add": "affine arithmetic near a graph input",
    "Cast": "input dtype conversion",
    "Clip": "input range clipping",
    "Div": "affine arithmetic near a graph input",
    "Gather": "possible channel selection or reordering",
    "Mul": "affine arithmetic near a graph input",
    "Pad": "spatial preprocessing",
    "Resize": "spatial preprocessing",
    "Slice": "possible crop or channel selection",
    "Sub": "affine arithmetic near a graph input",
    "Transpose": "input layout conversion",
}

# Traversal stops at learned or domain-specific operators. This keeps candidates scoped to the
# input prefix instead of reporting every arithmetic node in the model body.
INPUT_PREFIX_OPS = set(PREPROCESSING_OPS) | {
    "Concat",
    "Constant",
    "Identity",
    "Reshape",
    "Shape",
    "Squeeze",
    "Unsqueeze",
}


class MissingDependency(RuntimeError):
    pass


def import_onnx():
    try:
        import onnx
        from onnx import numpy_helper
    except ImportError as exc:
        raise MissingDependency(
            "inspect-onnx-model.py requires the optional dependency 'onnx'; "
            "install it in the conversion environment with: python3 -m pip install onnx"
        ) from exc
    return onnx, numpy_helper


def file_sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tensor_type(value_info, onnx):
    tensor = value_info.type.tensor_type
    dtype = dtype_name(tensor.elem_type, onnx)

    shape = []
    dynamic_dimensions = []
    if tensor.HasField("shape"):
        for index, dim in enumerate(tensor.shape.dim):
            if dim.HasField("dim_value"):
                shape.append(dim.dim_value)
            elif dim.HasField("dim_param"):
                shape.append(dim.dim_param)
                dynamic_dimensions.append({"index": index, "symbol": dim.dim_param})
            else:
                shape.append(None)
                dynamic_dimensions.append({"index": index, "symbol": None})

    return {
        "name": value_info.name,
        "dtype": dtype,
        "shape": shape,
        "dynamic_dimensions": dynamic_dimensions,
    }


def dtype_name(elem_type, onnx):
    try:
        return onnx.TensorProto.DataType.Name(elem_type)
    except ValueError:
        return "UNKNOWN({})".format(elem_type)


def initializer_info(tensor, onnx):
    return {
        "name": tensor.name,
        "dtype": dtype_name(tensor.data_type, onnx),
        "shape": list(tensor.dims),
        "external_data": {item.key: item.value for item in tensor.external_data},
    }


def scalar_value(value):
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def summarize_tensor(name, tensor, numpy_helper):
    summary = {"name": name, "shape": list(tensor.dims)}
    try:
        values = numpy_helper.to_array(tensor).reshape(-1)
        summary["sample"] = [scalar_value(value) for value in values[:16]]
        summary["value_count"] = int(values.size)
    except Exception as exc:  # External data may intentionally not be loaded.
        summary["sample_error"] = str(exc)
    return summary


def constant_tensors(graph, onnx, numpy_helper):
    constants = {
        tensor.name: summarize_tensor(tensor.name, tensor, numpy_helper)
        for tensor in graph.initializer
    }
    for node in graph.node:
        if node.op_type != "Constant" or not node.output:
            continue
        for attribute in node.attribute:
            if attribute.type == onnx.AttributeProto.TENSOR:
                constants[node.output[0]] = summarize_tensor(
                    node.output[0], attribute.t, numpy_helper
                )
                break
    return constants


def preprocessing_candidates(graph, constants, max_depth):
    consumers = {}
    for index, node in enumerate(graph.node):
        for tensor_name in node.input:
            consumers.setdefault(tensor_name, []).append((index, node))

    initializer_names = {tensor.name for tensor in graph.initializer}
    graph_inputs = [item.name for item in graph.input if item.name not in initializer_names]
    queue = deque((name, 0, name) for name in graph_inputs)
    visited = set()
    candidates = []

    while queue:
        tensor_name, depth, graph_input = queue.popleft()
        if depth > max_depth:
            continue
        for node_index, node in consumers.get(tensor_name, []):
            visit_key = (graph_input, node_index)
            if visit_key in visited:
                continue
            visited.add(visit_key)

            if node.op_type in PREPROCESSING_OPS:
                candidates.append(
                    {
                        "graph_input": graph_input,
                        "node_index": node_index,
                        "depth": depth,
                        "name": node.name or "<unnamed>",
                        "op_type": node.op_type,
                        "inputs": list(node.input),
                        "outputs": list(node.output),
                        "reason": PREPROCESSING_OPS[node.op_type],
                        "constant_inputs": [
                            constants[name] for name in node.input if name in constants
                        ],
                    }
                )

            if node.op_type in INPUT_PREFIX_OPS:
                for output_name in node.output:
                    queue.append((output_name, depth + 1, graph_input))

    return candidates


def inspect_model(path, max_depth=6):
    onnx, numpy_helper = import_onnx()
    model = onnx.load(str(path), load_external_data=False)
    graph = model.graph
    initializer_names = {tensor.name for tensor in graph.initializer}
    opsets = [
        {"domain": item.domain or "ai.onnx", "version": item.version}
        for item in model.opset_import
    ]
    constants = constant_tensors(graph, onnx, numpy_helper)

    return {
        "schema_version": 1,
        "artifact": {
            "path": str(path),
            "sha256": file_sha256(path),
            "size_bytes": path.stat().st_size,
        },
        "model": {
            "ir_version": model.ir_version,
            "opsets": opsets,
            "producer_name": model.producer_name or None,
            "producer_version": model.producer_version or None,
            "domain": model.domain or None,
            "model_version": model.model_version,
            "metadata": {item.key: item.value for item in model.metadata_props},
        },
        "graph": {
            "name": graph.name or None,
            "node_count": len(graph.node),
            "initializer_count": len(graph.initializer),
            "inputs": [
                tensor_type(item, onnx)
                for item in graph.input
                if item.name not in initializer_names
            ],
            "outputs": [tensor_type(item, onnx) for item in graph.output],
            "initializers": [initializer_info(item, onnx) for item in graph.initializer],
            "operator_counts": dict(sorted(Counter(node.op_type for node in graph.node).items())),
        },
        "preprocessing_candidates": preprocessing_candidates(graph, constants, max_depth),
        "limitations": [
            "Candidates near ONNX inputs do not prove the training or export preprocessing contract.",
            "ONNX inspection cannot reveal Toolkit2 mean_values/std_values used after ONNX loading.",
            "ONNX inspection cannot confirm whether the exported RKNN graph is INT8 or mixed precision.",
        ],
    }


def markdown_table(tensors):
    lines = ["| Name | Dtype | Shape | Dynamic dimensions |", "|---|---|---|---|"]
    for tensor in tensors:
        lines.append(
            "| `{}` | `{}` | `{}` | `{}` |".format(
                tensor["name"].replace("|", "\\|"),
                tensor["dtype"],
                json.dumps(tensor["shape"], ensure_ascii=True),
                json.dumps(tensor["dynamic_dimensions"], ensure_ascii=True),
            )
        )
    if not tensors:
        lines.append("| _none_ | | | |")
    return lines


def render_markdown(report):
    artifact = report["artifact"]
    model = report["model"]
    graph = report["graph"]
    lines = [
        "# ONNX Inspection Report",
        "",
        "This report describes the ONNX artifact. It is not proof of Toolkit2 normalization or RKNN graph precision.",
        "",
        "## Artifact",
        "",
        "- Path: `{}`".format(artifact["path"]),
        "- SHA-256: `{}`".format(artifact["sha256"]),
        "- Size: `{}` bytes".format(artifact["size_bytes"]),
        "- IR version: `{}`".format(model["ir_version"]),
        "- Opsets: `{}`".format(json.dumps(model["opsets"], ensure_ascii=True)),
        "- Producer: `{}` `{}`".format(model["producer_name"], model["producer_version"]),
        "- Metadata: `{}`".format(json.dumps(model["metadata"], sort_keys=True, ensure_ascii=True)),
        "",
        "## Graph Inputs",
        "",
    ]
    lines.extend(markdown_table(graph["inputs"]))
    lines.extend(["", "## Graph Outputs", ""])
    lines.extend(markdown_table(graph["outputs"]))
    lines.extend(["", "## Initializers", ""])
    if graph["initializers"]:
        lines.extend(
            [
                "- `{}`: dtype `{}`, shape `{}`, external data `{}`".format(
                    item["name"],
                    item["dtype"],
                    json.dumps(item["shape"], ensure_ascii=True),
                    json.dumps(item["external_data"], sort_keys=True, ensure_ascii=True),
                )
                for item in graph["initializers"]
            ]
        )
    else:
        lines.append("- _none_")
    lines.extend(
        [
            "",
            "## Operators",
            "",
            "- Nodes: `{}`".format(graph["node_count"]),
            "- Initializers: `{}`".format(graph["initializer_count"]),
            "- Counts: `{}`".format(
                json.dumps(graph["operator_counts"], sort_keys=True, ensure_ascii=True)
            ),
            "",
            "## Possible Input Preprocessing",
            "",
        ]
    )
    if report["preprocessing_candidates"]:
        for item in report["preprocessing_candidates"]:
            constants = json.dumps(item["constant_inputs"], sort_keys=True, ensure_ascii=True)
            lines.append(
                "- Input `{}` -> node {} `{}` (`{}`), depth {}: {}; constants: `{}`".format(
                    item["graph_input"],
                    item["node_index"],
                    item["name"],
                    item["op_type"],
                    item["depth"],
                    item["reason"],
                    constants,
                )
            )
    else:
        lines.append(
            "- No candidate was found in the inspected input prefix. This does not prove preprocessing is absent."
        )
    lines.extend(["", "## Limitations", ""])
    lines.extend("- {}".format(item) for item in report["limitations"])
    lines.append("")
    return "\n".join(lines)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Inspect ONNX identity, tensor metadata, and possible input preprocessing."
    )
    parser.add_argument("model", type=Path, help="ONNX model path")
    parser.add_argument(
        "--format", choices=("markdown", "json"), default="markdown", help="report format"
    )
    parser.add_argument("-o", "--output", type=Path, help="write the report to this path")
    parser.add_argument(
        "--max-depth",
        type=int,
        default=6,
        help="maximum input-prefix graph depth inspected for preprocessing candidates",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    if args.max_depth < 0:
        print("error: --max-depth must be non-negative", file=sys.stderr)
        return 2
    try:
        report = inspect_model(args.model, max_depth=args.max_depth)
    except MissingDependency as exc:
        print("error: {}".format(exc), file=sys.stderr)
        return 2
    except (OSError, ValueError) as exc:
        print("error: unable to inspect '{}': {}".format(args.model, exc), file=sys.stderr)
        return 1
    except Exception as exc:
        print("error: ONNX parsing failed for '{}': {}".format(args.model, exc), file=sys.stderr)
        return 1

    if args.format == "json":
        output = json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    else:
        output = render_markdown(report)

    try:
        if args.output:
            args.output.write_text(output, encoding="utf-8")
        else:
            sys.stdout.write(output)
    except OSError as exc:
        print("error: unable to write report: {}".format(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
