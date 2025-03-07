from hypothesis import given, assume, note, example
import hypothesis.strategies as st
import strategies
import six
import binascii

from blackboxprotobuf.lib.config import Config
from blackboxprotobuf.lib.types import length_delim
from blackboxprotobuf.lib.types import type_maps

if six.PY2:
    string_types = (unicode, str)
else:
    string_types = str

# Inverse checks. Ensure a value encoded by bbp decodes to the same value
@given(x=strategies.input_map["bytes"])
def test_bytes_inverse(x):
    encoded = length_delim.encode_bytes(x)
    decoded, pos = length_delim.decode_bytes(encoded, 0)
    assert isinstance(encoded, bytearray)
    assert isinstance(decoded, bytearray)
    assert pos == len(encoded)
    assert decoded == x


# Inverse checks. Ensure a value encoded by bbp decodes to the same value
@given(x=strategies.input_map["bytes"])
def test_bytes_guess_inverse(x):
    config = Config()
    # wrap the message in a new message so that it's a guess inside
    wrapper_typedef = {"1": {"type": "bytes"}}
    wrapper_message = {"1": x}

    encoded = length_delim.encode_lendelim_message(
        wrapper_message, config, wrapper_typedef
    )
    value, typedef, pos = length_delim.decode_lendelim_message(encoded, config, {})

    # would like to fail if it guesses wrong, but sometimes it might parse as a message
    assume(typedef["1"]["type"] == "bytes")

    assert isinstance(encoded, bytearray)
    assert isinstance(value["1"], bytearray)
    assert pos == len(encoded)
    assert value["1"] == x


@given(x=strategies.input_map["bytes"].map(binascii.hexlify))
def test_bytes_hex_inverse(x):
    encoded = length_delim.encode_bytes_hex(x)
    decoded, pos = length_delim.decode_bytes_hex(encoded, 0)
    assert isinstance(encoded, bytearray)
    assert isinstance(decoded, (bytearray, bytes))
    assert pos == len(encoded)
    assert decoded == x


@given(x=strategies.input_map["string"])
def test_string_inverse(x):
    encoded = length_delim.encode_bytes(x)
    decoded, pos = length_delim.decode_string(encoded, 0)
    assert isinstance(encoded, bytearray)
    assert isinstance(decoded, string_types)
    assert pos == len(encoded)
    assert decoded == x


@given(x=strategies.gen_message())
def test_message_inverse(x):
    config = Config()
    typedef, message = x
    encoded = length_delim.encode_lendelim_message(message, config, typedef)
    decoded, typedef_out, pos = length_delim.decode_lendelim_message(
        encoded, config, typedef, 0
    )
    note(encoded)
    note(typedef)
    note(typedef_out)
    assert isinstance(encoded, bytearray)
    assert isinstance(decoded, dict)
    assert pos == len(encoded)
    assert message == decoded


@given(x=strategies.gen_message(anon=True))
def test_anon_decode(x):
    config = Config()
    typedef, message = x
    encoded = length_delim.encode_lendelim_message(message, config, typedef)
    decoded, typedef_out, pos = length_delim.decode_lendelim_message(
        encoded, config, {}, 0
    )
    note("Original message: %r" % message)
    note("Decoded message: %r" % decoded)
    note("Original typedef: %r" % typedef)
    note("Decoded typedef: %r" % typedef_out)

    def check_message(orig, orig_typedef, new, new_typedef):
        for field_number in set(orig.keys()) | set(new.keys()):
            # verify all fields are there
            assert field_number in orig
            assert field_number in orig_typedef
            assert field_number in new
            assert field_number in new_typedef

            orig_values = orig[field_number]
            new_values = new[field_number]
            orig_type = orig_typedef[field_number]["type"]
            new_type = new_typedef[field_number]["type"]

            note("Parsing field# %s" % field_number)
            note("orig_values: %r" % orig_values)
            note("new_values: %r" % new_values)
            note("orig_type: %s" % orig_type)
            note("new_type: %s" % new_type)
            # Fields might be lists. Just convert everything to a list
            if not isinstance(orig_values, list):
                orig_values = [orig_values]
                assert not isinstance(new_values, list)
                new_values = [new_values]

            # if the types don't match, then try to convert them
            if new_type == "message" and orig_type in ["bytes", "string"]:
                # if the type is a message, we want to convert the orig type to a message
                # this isn't ideal, we'll be using the unintended type, but
                # best way to compare. Re-encoding a  message to binary might
                # not keep the field order
                new_field_typedef = new_typedef[field_number]["message_typedef"]
                for i, orig_value in enumerate(orig_values):
                    if orig_type == "bytes":
                        (
                            orig_values[i],
                            orig_field_typedef,
                            _,
                        ) = length_delim.decode_lendelim_message(
                            length_delim.encode_bytes(orig_value),
                            config,
                            new_field_typedef,
                        )
                    else:
                        # string value
                        (
                            orig_values[i],
                            orig_field_typedef,
                            _,
                        ) = length_delim.decode_lendelim_message(
                            length_delim.encode_string(orig_value),
                            config,
                            new_field_typedef,
                        )
                    orig_typedef[field_number]["message_typedef"] = orig_field_typedef
                orig_type = "message"

            if new_type == "string" and orig_type == "bytes":
                # our bytes were accidently valid string
                new_type = "bytes"
                for i, new_value in enumerate(new_values):
                    new_values[i], _ = length_delim.decode_bytes(
                        length_delim.encode_string(new_value), 0
                    )
            # sort the lists with special handling for dicts
            orig_values.sort(key=lambda x: x if not isinstance(x, dict) else x.items())
            new_values.sort(key=lambda x: x if not isinstance(x, dict) else x.items())
            for orig_value, new_value in zip(orig_values, new_values):
                if orig_type == "message":
                    check_message(
                        orig_value,
                        orig_typedef[field_number]["message_typedef"],
                        new_value,
                        new_typedef[field_number]["message_typedef"],
                    )
                else:
                    assert orig_value == new_value

    check_message(message, typedef, decoded, typedef_out)


@given(x=strategies.gen_message())
@example(x=({"1": {"seen_repeated": True, "type": "string"}}, {"1": [u"", u"0"]}))
@example(
    x=(
        {
            "1": {"seen_repeated": False, "type": "sfixed32"},
            "2": {"seen_repeated": True, "type": "string"},
        },
        {"1": 0, "2": [u"0", u"00"]},
    )
)
def test_message_guess_inverse(x):
    config = Config()
    type_def, message = x
    # wrap the message in a new message so that it's a guess inside
    wrapper_typedef = {"1": {"type": "message", "message_typedef": type_def}}
    wrapper_message = {"1": message}

    encoded = length_delim.encode_lendelim_message(
        wrapper_message, config, wrapper_typedef
    )
    note("Encoded length %d" % len(encoded))
    value, decoded_type, pos = length_delim.decode_lendelim_message(encoded, config, {})

    note(value)
    assert decoded_type["1"]["type"] == "message"

    assert isinstance(encoded, bytearray)
    assert isinstance(value, dict)
    assert isinstance(value["1"], dict)
    assert pos == len(encoded)


@given(x=strategies.input_map["packed_uint"])
def test_packed_uint_inverse(x):
    encoded = type_maps.ENCODERS["packed_uint"](x)
    decoded, pos = type_maps.DECODERS["packed_uint"](encoded, 0)
    assert isinstance(encoded, bytearray)
    assert pos == len(encoded)
    assert x == decoded


@given(x=strategies.input_map["packed_int"])
def test_packed_int_inverse(x):
    encoded = type_maps.ENCODERS["packed_int"](x)
    decoded, pos = type_maps.DECODERS["packed_int"](encoded, 0)
    assert isinstance(encoded, bytearray)
    assert pos == len(encoded)
    assert x == decoded


@given(x=strategies.input_map["packed_sint"])
def test_packed_sint_inverse(x):
    encoded = type_maps.ENCODERS["packed_sint"](x)
    decoded, pos = type_maps.DECODERS["packed_sint"](encoded, 0)
    assert isinstance(encoded, bytearray)
    assert pos == len(encoded)
    assert x == decoded


@given(x=strategies.input_map["packed_fixed32"])
def test_packed_fixed32_inverse(x):
    encoded = type_maps.ENCODERS["packed_fixed32"](x)
    decoded, pos = type_maps.DECODERS["packed_fixed32"](encoded, 0)
    assert isinstance(encoded, bytearray)
    assert pos == len(encoded)
    assert x == decoded


@given(x=strategies.input_map["packed_sfixed32"])
def test_packed_sfixed32_inverse(x):
    encoded = type_maps.ENCODERS["packed_sfixed32"](x)
    decoded, pos = type_maps.DECODERS["packed_sfixed32"](encoded, 0)
    assert isinstance(encoded, bytearray)
    assert pos == len(encoded)
    assert x == decoded


@given(x=strategies.input_map["packed_float"])
def test_packed_float_inverse(x):
    encoded = type_maps.ENCODERS["packed_float"](x)
    decoded, pos = type_maps.DECODERS["packed_float"](encoded, 0)
    assert isinstance(encoded, bytearray)
    assert pos == len(encoded)
    assert x == decoded


@given(x=strategies.input_map["packed_fixed64"])
def test_packed_fixed64_inverse(x):
    encoded = type_maps.ENCODERS["packed_fixed64"](x)
    decoded, pos = type_maps.DECODERS["packed_fixed64"](encoded, 0)
    assert isinstance(encoded, bytearray)
    assert pos == len(encoded)
    assert x == decoded


@given(x=strategies.input_map["packed_sfixed64"])
def test_packed_sfixed64_inverse(x):
    encoded = type_maps.ENCODERS["packed_sfixed64"](x)
    decoded, pos = type_maps.DECODERS["packed_sfixed64"](encoded, 0)
    assert isinstance(encoded, bytearray)
    assert pos == len(encoded)
    assert x == decoded


@given(x=strategies.input_map["packed_double"])
def test_packed_double_inverse(x):
    encoded = type_maps.ENCODERS["packed_double"](x)
    decoded, pos = type_maps.DECODERS["packed_double"](encoded, 0)
    assert isinstance(encoded, bytearray)
    assert pos == len(encoded)
    assert x == decoded
