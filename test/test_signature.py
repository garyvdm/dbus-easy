from pprint import pprint

import pytest

from dbus_ezy.signature import (
    Signature,
    SignatureBodyMismatchError,
    Variant,
    parse_signature,
    parse_single_type,
    signature_contains_type,
)


def param(text, expected, id=None):
    if not id:
        id = text
    return pytest.param(text, expected, id=id)


@pytest.mark.parametrize(
    "text,expected",
    [
        param(
            "s",
            Signature(
                text="s",
                type_code="r",
                children=(Signature(text="s", type_code="s"),),
            ),
        ),
        param(
            "sss",
            Signature(
                text="sss",
                type_code="r",
                children=(
                    Signature(text="s", type_code="s"),
                    Signature(text="s", type_code="s"),
                    Signature(text="s", type_code="s"),
                ),
            ),
        ),
        param(
            "asasass",
            Signature(
                text="asasass",
                type_code="r",
                children=(
                    Signature(
                        text="as",
                        type_code="a",
                        children=(Signature(text="s", type_code="s"),),
                    ),
                    Signature(
                        text="as",
                        type_code="a",
                        children=(Signature(text="s", type_code="s"),),
                    ),
                    Signature(
                        text="as",
                        type_code="a",
                        children=(Signature(text="s", type_code="s"),),
                    ),
                    Signature(text="s", type_code="s"),
                ),
            ),
        ),
        param(
            "(s)(s)(s)",
            Signature(
                text="(s)(s)(s)",
                type_code="r",
                children=(
                    Signature(
                        text="(s)",
                        type_code="(",
                        children=(Signature(text="s", type_code="s"),),
                    ),
                    Signature(
                        text="(s)",
                        type_code="(",
                        children=(Signature(text="s", type_code="s"),),
                    ),
                    Signature(
                        text="(s)",
                        type_code="(",
                        children=(Signature(text="s", type_code="s"),),
                    ),
                ),
            ),
        ),
    ],
)
def test_parse_signature(text: str, expected: Signature):
    signature = parse_signature(text)
    pprint(signature)
    assert signature == expected


@pytest.mark.parametrize(
    "text,expected",
    [
        param(
            "as",
            Signature(
                text="as",
                type_code="a",
                children=(Signature(text="s", type_code="s"),),
            ),
        ),
        param(
            "aas",
            Signature(
                text="aas",
                type_code="a",
                children=(
                    Signature(
                        text="as",
                        type_code="a",
                        children=(Signature(text="s", type_code="s"),),
                    ),
                ),
            ),
        ),
        param(
            "(sss)",
            Signature(
                text="(sss)",
                type_code="(",
                children=(
                    Signature(text="s", type_code="s"),
                    Signature(text="s", type_code="s"),
                    Signature(text="s", type_code="s"),
                ),
            ),
        ),
        param(
            "(s(s(s)))",
            Signature(
                text="(s(s(s)))",
                type_code="(",
                children=(
                    Signature(text="s", type_code="s"),
                    Signature(
                        text="(s(s))",
                        type_code="(",
                        children=(
                            Signature(text="s", type_code="s"),
                            Signature(
                                text="(s)",
                                type_code="(",
                                children=(Signature(text="s", type_code="s"),),
                            ),
                        ),
                    ),
                ),
            ),
        ),
        param(
            "a(ss)",
            Signature(
                text="a(ss)",
                type_code="a",
                children=(
                    Signature(
                        text="(ss)",
                        type_code="(",
                        children=(
                            Signature(text="s", type_code="s"),
                            Signature(text="s", type_code="s"),
                        ),
                    ),
                ),
            ),
        ),
        param(
            "a{ss}",
            Signature(
                text="a{ss}",
                type_code="a",
                children=(
                    Signature(
                        text="{ss}",
                        type_code="{",
                        children=(
                            Signature(text="s", type_code="s"),
                            Signature(text="s", type_code="s"),
                        ),
                    ),
                ),
            ),
        ),
        param(
            "a{s(ss)}",
            Signature(
                text="a{s(ss)}",
                type_code="a",
                children=(
                    Signature(
                        text="{s(ss)}",
                        type_code="{",
                        children=(
                            Signature(text="s", type_code="s"),
                            Signature(
                                text="(ss)",
                                type_code="(",
                                children=(
                                    Signature(text="s", type_code="s"),
                                    Signature(text="s", type_code="s"),
                                ),
                            ),
                        ),
                    ),
                ),
            ),
        ),
    ],
)
def test_parse_single_type(text: str, expected: Signature):
    signature = parse_single_type(text)
    pprint(signature)
    assert signature == expected


def test_contains_type_fd():
    signature = parse_signature("h")
    pprint(signature)
    assert signature_contains_type(signature, [0], "h")
    assert not signature_contains_type(signature, [0], "u")


def test_contains_type_array_fd():
    signature = parse_signature("ah")
    pprint(signature)
    assert signature_contains_type(signature, [[0]], "h")
    assert signature_contains_type(signature, [[0]], "a")
    assert not signature_contains_type(signature, [[0]], "u")


def test_contains_type_array_var():
    signature = parse_signature("av")
    pprint(signature)
    body = [[Variant("u", 0), Variant("i", 0), Variant("x", 0), Variant("v", Variant("s", "hi"))]]
    assert signature_contains_type(signature, body, "u")
    assert signature_contains_type(signature, body, "x")
    assert signature_contains_type(signature, body, "v")
    assert signature_contains_type(signature, body, "s")
    assert not signature_contains_type(signature, body, "o")


def test_contains_type_dict_str_var():
    signature = parse_signature("a{sv}")
    pprint(signature)
    body = {
        "foo": Variant("h", 0),
        "bar": Variant("i", 0),
        "bat": Variant("x", 0),
        "baz": Variant("v", Variant("o", "/hi")),
    }
    for expected in "hixvso":
        assert signature_contains_type(signature, [body], expected)
    assert not signature_contains_type(signature, [body], "b")


def test_invalid_variants():
    signature = parse_signature("a{sa{sv}}")
    pprint(signature)
    s_con = {
        "type": "802-11-wireless",
        "uuid": "1234",
        "id": "SSID",
    }

    s_wifi = {
        "ssid": "SSID",
        "mode": "infrastructure",
        "hidden": True,
    }

    s_wsec = {
        "key-mgmt": "wpa-psk",
        "auth-alg": "open",
        "psk": "PASSWORD",
    }

    s_ip4 = {"method": "auto"}
    s_ip6 = {"method": "auto"}

    con = {
        "connection": s_con,
        "802-11-wireless": s_wifi,
        "802-11-wireless-security": s_wsec,
        "ipv4": s_ip4,
        "ipv6": s_ip6,
    }

    with pytest.raises(SignatureBodyMismatchError):
        signature.verify([con])
