#!/usr/bin/env python3
"""Tiny deterministic LZSS block codec for native GAM resource images."""

from __future__ import annotations

from collections import defaultdict, deque

WINDOW = 4096
MIN_MATCH = 3
MAX_MATCH = 18


def compress(data: bytes) -> bytes:
    """Encode one block as flag groups plus 12-bit-distance matches."""

    positions: defaultdict[bytes, deque[int]] = defaultdict(deque)
    output = bytearray()
    cursor = 0
    while cursor < len(data):
        flag_offset = len(output)
        output.append(0)
        flags = 0
        for bit in range(8):
            if cursor >= len(data):
                break
            best_length = 0
            best_distance = 0
            key = data[cursor : cursor + MIN_MATCH]
            candidates = positions[key]
            while candidates and cursor - candidates[0] > WINDOW:
                candidates.popleft()
            for previous in reversed(candidates):
                distance = cursor - previous
                limit = min(MAX_MATCH, len(data) - cursor)
                length = MIN_MATCH
                while length < limit and data[previous + length] == data[cursor + length]:
                    length += 1
                if length > best_length:
                    best_length = length
                    best_distance = distance
                    if length == MAX_MATCH:
                        break
            if best_length >= MIN_MATCH:
                token = ((best_length - MIN_MATCH) << 12) | (best_distance - 1)
                output.extend((token & 0xFF, token >> 8))
                consumed = best_length
            else:
                flags |= 1 << bit
                output.append(data[cursor])
                consumed = 1
            end = cursor + consumed
            for position in range(cursor, end):
                if position + MIN_MATCH <= len(data):
                    chain = positions[data[position : position + MIN_MATCH]]
                    chain.append(position)
                    # Long runs otherwise retain thousands of equivalent
                    # candidates; the newest 64 are sufficient for 18 bytes.
                    while len(chain) > 64:
                        chain.popleft()
            cursor = end
        output[flag_offset] = flags
    return bytes(output)


def decompress(data: bytes, expected_size: int) -> bytes:
    output = bytearray()
    cursor = 0
    while len(output) < expected_size:
        if cursor >= len(data):
            raise ValueError("truncated LZSS flag byte")
        flags = data[cursor]
        cursor += 1
        for bit in range(8):
            if len(output) >= expected_size:
                break
            if flags & (1 << bit):
                if cursor >= len(data):
                    raise ValueError("truncated LZSS literal")
                output.append(data[cursor])
                cursor += 1
                continue
            if cursor + 2 > len(data):
                raise ValueError("truncated LZSS match")
            token = data[cursor] | data[cursor + 1] << 8
            cursor += 2
            distance = (token & 0x0FFF) + 1
            length = (token >> 12) + MIN_MATCH
            if distance > len(output):
                raise ValueError("invalid LZSS distance")
            for _ in range(length):
                output.append(output[-distance])
                if len(output) == expected_size:
                    break
    if cursor != len(data):
        raise ValueError("trailing LZSS bytes")
    return bytes(output)
