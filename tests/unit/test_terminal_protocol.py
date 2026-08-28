from core.terminal.protocol import parse_client_message
import json

def test_input_ok():
    assert parse_client_message(json.dumps({"type":"input","data":"ls\r"})) == {"type":"input","data":"ls\r"}

def test_resize_ok():
    assert parse_client_message(json.dumps({"type":"resize","cols":80,"rows":24})) == {"type":"resize","cols":80,"rows":24}

def test_ping():
    assert parse_client_message(json.dumps({"type":"ping"}))["type"]=="ping"

def test_unknown():
    r = parse_client_message(json.dumps({"type":"foo"}))
    assert r["type"]=="error"

def test_invalid_json():
    assert parse_client_message("not json")["type"]=="error"

def test_resize_out_of_range():
    assert parse_client_message(json.dumps({"type":"resize","cols":1,"rows":1}))["type"]=="error"

def test_input_not_string():
    assert parse_client_message(json.dumps({"type":"input","data":123}))["type"]=="error"

def test_bytes_input():
    assert parse_client_message(b'{"type":"ping"}')["type"]=="ping"
