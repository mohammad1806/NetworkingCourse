"""
Shared protocol helpers for the Blackjack networking assignment.

Packet formats (network byte order / big-endian):
- Offer (UDP):    cookie(4) type(1)=0x2 tcp_port(2) server_name(32)
- Request (TCP):  cookie(4) type(1)=0x3 rounds(1) client_name(32)
- Payload (TCP):
    Client -> Server: cookie(4) type(1)=0x4 decision(5)  ("Hittt" or "Stand")
    Server -> Client: cookie(4) type(1)=0x4 result(1) rank(2) suit(1)
"""

from __future__ import annotations
import struct
from dataclasses import dataclass

MAGIC_COOKIE = 0xABCDDCBA

MSG_OFFER   = 0x2
MSG_REQUEST = 0x3
MSG_PAYLOAD = 0x4

# Server -> client result byte
RES_NOT_OVER = 0x0
RES_TIE      = 0x1
RES_LOSS     = 0x2  # client loses
RES_WIN      = 0x3  # client wins

SUITS = ("H", "D", "C", "S")  # Heart, Diamond, Club, Spade

OFFER_STRUCT   = struct.Struct("!I B H 32s")     # 4+1+2+32 = 39
REQUEST_STRUCT = struct.Struct("!I B B 32s")     # 4+1+1+32 = 38
CLIENT_PAYLOAD_STRUCT = struct.Struct("!I B 5s") # 4+1+5 = 10
SERVER_PAYLOAD_STRUCT = struct.Struct("!I B B H B") # 4+1+1+2+1 = 9

def _fixed_name_bytes(name: str) -> bytes:
    b = name.encode("utf-8", errors="ignore")
    b = b[:32]
    return b + b"\x00" * (32 - len(b))

def _decode_fixed_name(b: bytes) -> str:
    return b.split(b"\x00", 1)[0].decode("utf-8", errors="ignore")

@dataclass(frozen=True)
class Offer:
    tcp_port: int
    server_name: str

def pack_offer(tcp_port: int, server_name: str) -> bytes:
    return OFFER_STRUCT.pack(MAGIC_COOKIE, MSG_OFFER, tcp_port, _fixed_name_bytes(server_name))

def unpack_offer(data: bytes) -> Offer | None:
    if len(data) < OFFER_STRUCT.size:
        return None
    cookie, mtype, tcp_port, name = OFFER_STRUCT.unpack(data[:OFFER_STRUCT.size])
    if cookie != MAGIC_COOKIE or mtype != MSG_OFFER:
        return None
    return Offer(tcp_port=int(tcp_port), server_name=_decode_fixed_name(name))

@dataclass(frozen=True)
class Request:
    rounds: int
    client_name: str

def pack_request(rounds: int, client_name: str) -> bytes:
    rounds = int(rounds) & 0xFF
    return REQUEST_STRUCT.pack(MAGIC_COOKIE, MSG_REQUEST, rounds, _fixed_name_bytes(client_name))

def unpack_request(data: bytes) -> Request | None:
    if len(data) < REQUEST_STRUCT.size:
        return None
    cookie, mtype, rounds, name = REQUEST_STRUCT.unpack(data[:REQUEST_STRUCT.size])
    if cookie != MAGIC_COOKIE or mtype != MSG_REQUEST:
        return None
    return Request(rounds=int(rounds), client_name=_decode_fixed_name(name))

def pack_client_decision(decision: str) -> bytes:
    # decision must be exactly 5 bytes: "Hittt" or "Stand"
    if decision not in ("Hittt", "Stand"):
        raise ValueError("decision must be 'Hittt' or 'Stand'")
    return CLIENT_PAYLOAD_STRUCT.pack(MAGIC_COOKIE, MSG_PAYLOAD, decision.encode("ascii"))

def unpack_client_decision(data: bytes) -> str | None:
    if len(data) < CLIENT_PAYLOAD_STRUCT.size:
        return None
    cookie, mtype, d = CLIENT_PAYLOAD_STRUCT.unpack(data[:CLIENT_PAYLOAD_STRUCT.size])
    if cookie != MAGIC_COOKIE or mtype != MSG_PAYLOAD:
        return None
    try:
        s = d.decode("ascii", errors="ignore")
    except Exception:
        return None
    return s if s in ("Hittt", "Stand") else None

def pack_server_update(result: int, rank: int = 0, suit: int = 0) -> bytes:
    # rank: 0 or 1..13 ; suit: 0..3 (only meaningful if rank != 0)
    return SERVER_PAYLOAD_STRUCT.pack(MAGIC_COOKIE, MSG_PAYLOAD, result & 0xFF, int(rank) & 0xFFFF, int(suit) & 0xFF)

def unpack_server_update(data: bytes) -> tuple[int,int,int] | None:
    if len(data) < SERVER_PAYLOAD_STRUCT.size:
        return None
    cookie, mtype, res, rank, suit = SERVER_PAYLOAD_STRUCT.unpack(data[:SERVER_PAYLOAD_STRUCT.size])
    if cookie != MAGIC_COOKIE or mtype != MSG_PAYLOAD:
        return None
    return int(res), int(rank), int(suit)

def card_value(rank: int) -> int:
    # rank 1..13 ; 1=Ace
    #if rank == 1:
    #    return 11
    if rank >= 11:
        return 10
    return rank

def card_str(rank: int, suit: int) -> str:
    if rank == 0:
        return "—"
    r = {1:"A", 11:"J", 12:"Q", 13:"K"}.get(rank, str(rank))
    s = SUITS[suit] if 0 <= suit < 4 else str(suit)
    return f"{r},{s}"
