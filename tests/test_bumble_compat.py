from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from bumble import l2cap
from wiichinahook.bumble_compat import normalize_configuration_options, install_l2cap_hint_compat


def test_captured_clone_configuration_hint_is_optional():
    # Actual signaling option observed in the user's successful-auth trace.
    assert normalize_configuration_options(bytes.fromhex('80 02 20 03')) == b''
    assert normalize_configuration_options(bytes.fromhex('81 02 a0 02')) == bytes.fromhex('01 02 a0 02')
    # Unknown mandatory options must continue to be rejected by Bumble.
    assert normalize_configuration_options(bytes.fromhex('09 01 ff')) == bytes.fromhex('09 01 ff')
    with pytest.raises(ValueError):
        normalize_configuration_options(bytes.fromhex('80 02 20'))


def test_adapter_does_not_modify_original_packet():
    original=Mock()
    manager=SimpleNamespace(on_l2cap_configure_request=original)
    install_l2cap_hint_compat(manager)
    request=l2cap.L2CAP_Configure_Request(identifier=1,destination_cid=0x40,flags=0,options=bytes.fromhex('80 02 20 03'))
    manager.on_l2cap_configure_request(SimpleNamespace(peer_address='clone'),1,request)
    assert original.call_args.args[2].options == b''
    assert request.options == bytes.fromhex('80 02 20 03')
