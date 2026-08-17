#!/usr/bin/env python3
"""Focused checks for compressed request-body handling in vision_proxy."""

import base64
import gzip
import importlib.util
import json
import os
import sys
import zlib


PROXY = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "vision_proxy.py")
sys.path.insert(0, os.path.dirname(PROXY))
ZSTD_FIXTURE = base64.b64decode(
    "KLUv/SCRbQMAQgYVGYCpGgN4agW4pCOzJ1shzES6VBL05YCjqI/RiEa8lFKIYJAS"
    "aiAc7QFSV9H5QkCTDmXKTA6cc6QmC51ZS49pTu1p8HCenmJfFPKFr6nJ7Hwl5NiL"
    "CAA0JVcBtIhiwoWtDNiZKGZjGKuCAg=="
)
ZSTD_SIZELESS_FIXTURE = base64.b64decode(
    "KLUv/QAAbQMAQgYVGYCpGgN4agW4pCOzJ1shzES6VBL05YCjqI/RiEa8lFKIYJAS"
    "aiAc7QFSV9H5QkCTDmXKTA6cc6QmC51ZS49pTu1p8HCenmJfFPKFr6nJ7Hwl5NiL"
    "CAA0JVcBtIhiwoWtDNiZKGZjGKuCAg=="
)
RAW = (b'{"model":"m","input":[{"type":"function_call_output",'
       b'"call_id":"c1","output":[{"type":"input_image",'
       b'"image_url":"data:image/png;base64,AAAA"}]}]}')


def load_proxy():
    spec = importlib.util.spec_from_file_location("vision_proxy_content_encoding", PROXY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    module = load_proxy()
    assert module._decode_request_body(ZSTD_FIXTURE, "zstd") == RAW
    assert module._decode_request_body(ZSTD_SIZELESS_FIXTURE, "zstd") == RAW
    assert module._decode_request_body(gzip.compress(RAW), "gzip") == RAW
    assert module._decode_request_body(zlib.compress(RAW), "deflate") == RAW
    raw_encoder = zlib.compressobj(wbits=-zlib.MAX_WBITS)
    raw_deflate = raw_encoder.compress(RAW) + raw_encoder.flush()
    assert module._decode_request_body(raw_deflate, "deflate") == RAW
    layered = zlib.compress(gzip.compress(RAW))
    assert module._decode_request_body(layered, "gzip, deflate") == RAW

    incoming = [("Content-Encoding", "gzip"), ("Content-Encoding", "deflate"),
                ("Content-Type", "application/json")]
    assert module._header_values(incoming, "content-encoding") == "gzip, deflate"
    forwarded = module.Proxy(1, "http://example", "", False, False)._upstream_headers(incoming)
    assert not any(key.lower() == "content-encoding" for key, _ in forwarded)
    assert ("Content-Type", "application/json") in forwarded

    try:
        module._decode_request_body(RAW, "br")
    except ValueError as exc:
        assert "Unsupported Content-Encoding: br" in str(exc)
    else:
        raise AssertionError("unsupported content encodings must fail explicitly")

    original_limit = module.MAX_DECODED_BODY_BYTES
    module.MAX_DECODED_BODY_BYTES = len(RAW)
    assert module._decode_request_body(gzip.compress(RAW), "gzip") == RAW
    module.MAX_DECODED_BODY_BYTES = len(RAW) - 1
    try:
        module._decode_request_body(gzip.compress(RAW), "gzip")
    except module._RequestBodyTooLarge:
        pass
    else:
        raise AssertionError("decoded request bodies must enforce the size limit")
    finally:
        module.MAX_DECODED_BODY_BYTES = original_limit

    parsed = json.loads(module._decode_request_body(ZSTD_FIXTURE, "zstd"))
    assert parsed["input"][0]["type"] == "function_call_output"
    print("REQUEST CONTENT-ENCODING PASS")


if __name__ == "__main__":
    main()
