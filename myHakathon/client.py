from __future__ import annotations

import argparse
import socket
import time
from typing import Tuple

import myHakathon.protocol as P

DEFAULT_UDP_PORT = 13117  # must match server broadcast target
BIND_ADDR = "0.0.0.0"

def read_exact(sock: socket.socket, n: int) -> bytes:
    chunks = []
    got = 0
    while got < n:
        b = sock.recv(n - got)
        if not b:
            raise ConnectionError("server closed connection")
        chunks.append(b)
        got += len(b)
    return b"".join(chunks)

def prompt_rounds() -> int:
    while True:
        try:
            x = int(input("How many rounds do you want to play? : ").strip())
            if 1 <= x <= 255:
                return x
        except Exception:
            pass
        print("Please enter an integer between 1 and 255.")

def prompt_decision() -> str:
    while True:
        ans = input("Hit or Stand? ").strip().lower()
        if ans in ("hit", "h"):
            return "Hittt"
        if ans in ("stand", "s"):
            return "Stand"
        print("Type 'Hit' or 'Stand'.")

def listen_for_offer(udp_port: int, timeout: float = 0.0) -> Tuple[str, int, str]:
    """
    Returns: (server_ip, tcp_port, server_name)
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind((BIND_ADDR, udp_port))
    if timeout > 0:
        s.settimeout(timeout)
    print("Client started, listening for offer requests...")
    while True:
        data, (ip, _port) = s.recvfrom(2048)
        offer = P.unpack_offer(data)
        if offer:
            print(f"Received offer from {ip} (server='{offer.server_name}', tcp_port={offer.tcp_port})")
            s.close()
            return ip, offer.tcp_port, offer.server_name

def play_session(server_ip: str, tcp_port: int, team_name: str, rounds: int) -> Tuple[int, int, int]:
    """
    Plays exactly `rounds` rounds over a single TCP connection.
    Returns: (wins, losses, ties)
    """
    wins = losses = ties = 0

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((server_ip, tcp_port))
    sock.sendall(P.pack_request(rounds, team_name))

    for r in range(1, rounds + 1):
        print(f"\n=== Round {r}/{rounds} ===")

        # State:
        # Expect initial 3 server updates: player card, player card, dealer upcard
        player_sum = 0
        dealer_sum = 0

        # helper to read one server update
        def recv_update():
            b = read_exact(sock, P.SERVER_PAYLOAD_STRUCT.size)
            parsed = P.unpack_server_update(b)
            if not parsed:
                raise ConnectionError("invalid server payload")
            return parsed  # (result, rank, suit)

        # Initial three cards
        res, rank, suit = recv_update()
        player_sum += P.card_value(rank)
        print(f"Player card: {P.card_str(rank, suit)} (sum={player_sum})")

        res, rank, suit = recv_update()
        player_sum += P.card_value(rank)
        print(f"Player card: {P.card_str(rank, suit)} (sum={player_sum})")

        res, rank, suit = recv_update()
        dealer_sum += P.card_value(rank)
        print(f"Dealer shows: {P.card_str(rank, suit)} (visible sum={dealer_sum})")

        # Player turn loop
        # Server will wait for client decisions. After each Hittt it sends one card (result=0).
        while True:
            decision = prompt_decision()
            sock.sendall(P.pack_client_decision(decision))
            print(f"-> Sent decision: {decision}")

            if decision == "Stand":
                break

            # Receive new player card (or possibly immediate final if bug, but server sends card then maybe final)
            res, rank, suit = recv_update()
            if res != P.RES_NOT_OVER:
                # unexpected, but handle
                pass
            player_sum += P.card_value(rank)
            print(f"Player hits: {P.card_str(rank, suit)} (sum={player_sum})")

            # After a bust, server sends a final result message (rank=0)
            if player_sum > 21:
                res, rank, suit = recv_update()
                if res == P.RES_LOSS:
                    print("Result: LOSS (bust)")
                    losses += 1
                elif res == P.RES_TIE:
                    print("Result: TIE")
                    ties += 1
                else:
                    print("Result: WIN")
                    wins += 1
                # round over
                break

        # If player didn't bust, dealer phase begins:
        if player_sum <= 21:
            # Dealer reveals downcard (result=0)
            res, rank, suit = recv_update()
            dealer_sum += P.card_value(rank)
            print(f"Dealer reveals: {P.card_str(rank, suit)} (sum={dealer_sum})")

            # Dealer may hit multiple times (all res=0) then a final res!=0
            while True:
                res, rank, suit = recv_update()
                if res == P.RES_NOT_OVER:
                    dealer_sum += P.card_value(rank)
                    print(f"Dealer hits: {P.card_str(rank, suit)} (sum={dealer_sum})")
                    continue

                # Final result message (rank likely 0)
                if res == P.RES_WIN:
                    print("Result: WIN")
                    wins += 1
                elif res == P.RES_LOSS:
                    print("Result: LOSS")
                    losses += 1
                else:
                    print("Result: TIE")
                    ties += 1
                break

    sock.close()
    return wins, losses, ties

def main():
    ap = argparse.ArgumentParser(description="Blackjack Player Client")
    ap.add_argument("--team", default="TeamClient", help="Client team name (<=32 bytes UTF-8 recommended)")
    ap.add_argument("--udp-port", type=int, default=DEFAULT_UDP_PORT, help="UDP port to listen on for offers")
    args = ap.parse_args()

    while True:
        rounds = prompt_rounds()
        server_ip, tcp_port, server_name = listen_for_offer(args.udp_port, 60)
        try:
            wins, losses, ties = play_session(server_ip, tcp_port, args.team, rounds)
            played = wins + losses + ties
            win_rate = (wins / played) if played else 0.0
            print(f"\nFinished playing {played} rounds, win rate: {win_rate:.3f} (W={wins}, L={losses}, T={ties})")
        except (ConnectionError, OSError) as e:
            print(f"Connection/session error: {e}")
        print("\nReturning to listen for offers...\n")
        time.sleep(0.5)

if __name__ == "__main__":
    main()
