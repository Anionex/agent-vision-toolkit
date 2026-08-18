#!/usr/bin/env python3
"""Focused checks for compressed request-body handling in vision_proxy."""

import base64
import asyncio
import gzip
import importlib.util
import json
import os
import sys
import zlib
from contextlib import asynccontextmanager


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
ZSTD_CHECKSUM_FIXTURE = base64.b64decode(
    "KLUv/SQa0QAAeyJtb2RlbCI6Im0iLCJpbnB1dCI6Im9rIn0wlGBP"
)
ZSTD_CHECKSUM_RAW = b'{"model":"m","input":"ok"}'
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

    try:
        module._decode_request_body(RAW, "gzip, gzip, gzip, gzip, gzip")
    except module._InvalidContentEncoding as exc:
        assert "Too many Content-Encoding layers" in str(exc)
    else:
        raise AssertionError("content encoding layers must be bounded")

    try:
        module._decode_request_body(zlib.compress(RAW) + b"JUNK", "deflate")
    except module._InvalidContentEncoding as exc:
        assert "trailing data" in str(exc)
    else:
        raise AssertionError("deflate trailing data must not be discarded")

    original_loader = module._load_zstd_library
    module._load_zstd_library = lambda: type(
        "UnavailableZstd", (), {"ZSTD_createDStream": lambda self: 0})()
    try:
        module._decompress_zstd_native(bytearray(ZSTD_FIXTURE))
    except module._ContentDecoderError:
        pass
    else:
        raise AssertionError("decoder initialization failures must be server errors")
    finally:
        module._load_zstd_library = original_loader

    internal_error = type(
        "InternalZstdError", (), {
            "ZSTD_isError": lambda self, result: 1,
            "ZSTD_getErrorCode": lambda self, result: self.error_code,
            "ZSTD_getErrorName": lambda self, result: b"internal decoder error",
        })()
    for code in (60, 64, 104, 105, 106, 107):
        internal_error.error_code = code
        try:
            module._raise_zstd_decode_error(internal_error, 1)
        except module._ContentDecoderError:
            pass
        else:
            raise AssertionError(
                f"runtime decoder internal error code {code} must be a server error")

    invalid_frame = type(
        "InvalidZstdFrame", (), {
            "ZSTD_isError": lambda self, result: 1,
            "ZSTD_getErrorCode": lambda self, result: 20,
            "ZSTD_getErrorName": lambda self, result: b"corrupt frame",
        })()
    try:
        module._raise_zstd_decode_error(invalid_frame, 1)
    except module._InvalidContentEncoding:
        pass
    else:
        raise AssertionError("invalid zstd frames must remain client errors")

    try:
        module._raise_python_zstd_error(
            RuntimeError("Allocation error : not enough memory"))
    except module._ContentDecoderError:
        pass
    else:
        raise AssertionError("Python zstd allocation failures must be server errors")

    for message in (
        "Operation not authorized at current processing stage",
        "Context should be init first",
        "Destination buffer is too small",
        "Operation on NULL destination buffer",
        "Operation made no progress over multiple calls, due to output buffer being full",
        "Operation made no progress over multiple calls, due to input being empty",
    ):
        try:
            module._raise_python_zstd_error(RuntimeError(message))
        except module._ContentDecoderError:
            pass
        else:
            raise AssertionError(f"Python zstd internal error was misclassified: {message}")

    try:
        module._raise_python_zstd_error(RuntimeError("Unknown frame descriptor"))
    except module._InvalidContentEncoding:
        pass
    else:
        raise AssertionError("Python zstd frame errors must remain client errors")

    try:
        module._configure_zstd_library(object())
    except AttributeError:
        pass
    else:
        raise AssertionError("native zstd candidates must expose every required symbol")

    try:
        import zstandard
    except ImportError:
        pass
    else:
        assert module._decompress_zstandard_fallback(
            ZSTD_CHECKSUM_FIXTURE, zstandard) == ZSTD_CHECKSUM_RAW
        assert module._decompress_zstandard_fallback(
            ZSTD_CHECKSUM_FIXTURE + ZSTD_CHECKSUM_FIXTURE,
            zstandard,
        ) == ZSTD_CHECKSUM_RAW * 2
        for truncated in (
            ZSTD_CHECKSUM_FIXTURE[:-1],
            ZSTD_CHECKSUM_FIXTURE[:-4],
            ZSTD_CHECKSUM_FIXTURE + ZSTD_CHECKSUM_FIXTURE[:-1],
            ZSTD_CHECKSUM_FIXTURE + b"JUNK",
        ):
            try:
                module._decompress_zstandard_fallback(truncated, zstandard)
            except module._InvalidContentEncoding:
                pass
            else:
                raise AssertionError("third-party zstd fallback accepted a truncated frame")

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
    asyncio.run(_concurrent_compressed_requests_do_not_wait_for_upstream())
    asyncio.run(_identity_body_read_keeps_original_no_timeout())
    print("REQUEST CONTENT-ENCODING PASS")


class _FakeUpstreamResponse:
    def close(self):
        pass


async def _http_exchange(port, request):
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(request)
    await writer.drain()
    data = await reader.read()
    writer.close()
    try:
        await writer.wait_closed()
    except Exception:
        pass
    return data


@asynccontextmanager
async def _patched_proxy(module, read_timeout, upstream_delay):
    proxy = module.Proxy(1, "http://127.0.0.1:9", "", False, False)
    original_timeout = module.REQUEST_BODY_READ_TIMEOUT
    original_rewrite = module._rewrite_image_inputs
    original_open = module.Proxy._open_upstream
    original_send = module.Proxy._send_response

    async def no_rewrite(parsed):
        return False

    async def delayed_open(self, method, path, body, headers):
        if upstream_delay:
            await asyncio.sleep(upstream_delay)
        return _FakeUpstreamResponse()

    async def send_ok(self, writer, response):
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok")
        await writer.drain()

    module.REQUEST_BODY_READ_TIMEOUT = read_timeout
    module._rewrite_image_inputs = no_rewrite
    module.Proxy._open_upstream = delayed_open
    module.Proxy._send_response = send_ok
    try:
        server = await asyncio.start_server(proxy.handle, "127.0.0.1", 0)
        async with server:
            yield proxy, server.sockets[0].getsockname()[1]
    finally:
        module.REQUEST_BODY_READ_TIMEOUT = original_timeout
        module._rewrite_image_inputs = original_rewrite
        module.Proxy._open_upstream = original_open
        module.Proxy._send_response = original_send


async def _concurrent_compressed_requests_do_not_wait_for_upstream():
    module = load_proxy()
    async with _patched_proxy(module, read_timeout=0.4, upstream_delay=1.0) as (proxy, port):
        request = (
            f"POST /responses HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n"
            "Content-Type: application/json\r\nContent-Encoding: zstd\r\n"
            f"Content-Length: {len(ZSTD_FIXTURE)}\r\nConnection: close\r\n\r\n"
        ).encode() + ZSTD_FIXTURE
        responses = await asyncio.gather(
            _http_exchange(port, request),
            _http_exchange(port, request),
        )
    for data in responses:
        assert b"200 OK" in data, data
        assert b"408" not in data, data


async def _identity_body_read_keeps_original_no_timeout():
    module = load_proxy()
    async with _patched_proxy(module, read_timeout=0.2, upstream_delay=0.0) as (proxy, port):
        body = b'{"model":"m","input":"ok"}'
        head = (
            f"POST /responses HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n"
            "Content-Type: application/json\r\n"
            f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n"
        ).encode()
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(head)
        await writer.drain()
        await asyncio.sleep(0.3)
        writer.write(body)
        await writer.drain()
        data = await reader.read()
        writer.close()
        await writer.wait_closed()
        assert b"200 OK" in data, data


if __name__ == "__main__":
    main()
