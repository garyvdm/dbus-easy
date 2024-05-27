import ast
import inspect
from typing import Any, Callable, List, Mapping, Sequence, Tuple, Union

from ..signature import Signature, Variant, parse_signature


def replace_fds_with_idx(
    signature: Union[str, Signature], body: List[Any]
) -> Tuple[List[Any], List[int]]:
    """Take the high level body format and convert it into the low level body
    format. Type 'h' refers directly to the fd in the body. Replace that with
    an index and return the corresponding list of unix fds that can be set on
    the Message"""
    if type(signature) is str:
        signature = parse_signature(signature)

    unix_fds = []

    def _replace(fd):
        try:
            return unix_fds.index(fd)
        except ValueError:
            unix_fds.append(fd)
            return len(unix_fds) - 1

    return _replace_fds(body, signature, _replace), unix_fds


def replace_idx_with_fds(
    signature: Union[str, Signature], body: List[Any], unix_fds: List[int]
) -> List[Any]:
    """Take the low level body format and return the high level body format.
    Type 'h' refers to an index in the unix_fds array. Replace those with the
    actual file descriptor or `None` if one does not exist."""
    if type(signature) is str:
        signature = parse_signature(signature)

    def _replace(idx):
        try:
            return unix_fds[idx]
        except IndexError:
            return None

    return _replace_fds(body, signature, _replace)


def _replace_fds(body_obj: Any, signature: Signature, replace_fn: Callable[[Any], Any]):
    """Replace any type 'h' with the value returned by replace_fn() given the
    value of the fd field. This is used by the high level interfaces which
    allow type 'h' to be the fd directly instead of an index in an external
    array such as in the spec."""

    if not any(type_code in signature.text for type_code in "hv"):
        return body_obj

    if signature.type_code == "h":
        return replace_fn(body_obj)

    if signature.type_code == "v":
        assert isinstance(body_obj, Variant)
        return Variant(
            body_obj.signature, _replace_fds(body_obj.value, body_obj.signature, replace_fn)
        )

    if signature.type_code == "r" or signature.type_code == "(":
        assert isinstance(body_obj, Sequence)
        return [
            _replace_fds(child_obj, child_sig, replace_fn)
            for child_obj, child_sig in zip(body_obj, signature.children)
        ]

    if signature.type_code == "a":
        item_sig = signature.children[0]
        if item_sig.type_code == "{":
            assert isinstance(body_obj, Mapping)
            value_sig = item_sig.children[1]
            return {
                key: _replace_fds(value, value_sig, replace_fn) for key, value in body_obj.items()
            }
        else:
            assert isinstance(body_obj, Sequence)
            return [_replace_fds(item, item_sig, replace_fn) for item in body_obj]

    raise AssertionError("No return happened.")


def select_annotated_metadata(annotation) -> str:
    """
    An PEP 593 Annotated instance (and the typing_extensions versions of that)
    may contain multiple types of metadata, designed to be used by multiple
    different libraries. To support that we only select string constants from
    the annotation metadata and ignore others
    """
    for meta_annotation in annotation.__metadata__:
        if type(meta_annotation) is str:
            return meta_annotation
    raise ValueError("service annotation using PEP 593 Annotated must contain a string constant")


def parse_annotation(annotation) -> str:
    """
    Because of PEP 563, if `from __future__ import annotations` is used in code
    or on Python version >=3.10 where this is the default, return annotations
    from the `inspect` module will return annotations as "forward definitions".
    In this case, we must eval the result which we do only when given a string
    constant.
    """

    def raise_value_error():
        raise ValueError(f"service annotations must be a string constant (got {annotation})")

    if not annotation or annotation is inspect.Signature.empty:
        return ""

    # checking with hasattr because th python 3.6 version of
    # typing_extensions.Annotated does not support isinstance
    if hasattr(annotation, "__metadata__"):
        annotation = select_annotated_metadata(annotation)

    if type(annotation) is not str:
        raise_value_error()
    try:
        body = ast.parse(annotation).body
        if len(body) == 1 and type(body[0].value) is ast.Constant:
            if type(body[0].value.value) is not str:
                raise_value_error()
            return body[0].value.value
    except SyntaxError:
        pass

    return annotation
