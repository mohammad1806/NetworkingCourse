from __future__ import annotations

import argparse
import random
import socket
import threading
import time
from typing import List, Tuple

import protocol as P

DEFAULT_UDP_PORT = 13117  # common in similar assignments; can be overridden
BROADCAST_ADDR = "255.255.255.255"

Card = Tuple[int, int]  # (rank 1..13, suit 0..3)

def fresh_shuffled_deck() -> List[Card]:
    deck: List[Card] = [(rank, suit) for suit in range(4) for rank in range(1, 14)]
    random.shuffle(deck)
    return deck

def read_exact(sock: socket.socket, n: int) -> bytes:
    chunks = []
    got = 0
    while got < n:
        b = sock.recv(n - got)
        if not b:
            raise ConnectionError("peer closed connection")
        chunks.append(b)
        got += len(b)
    return b"".join(chunks)

def send_update(sock: socket.socket, result: int, card: Card | None) -> None:
    if card is None:
        data = P.pack_server_update(result, 0, 0)
    else:
        rank, suit = card
        data = P.pack_server_update(result, rank, suit)
    sock.sendall(data)

def sum_cards(cards: List[Card]) -> int:
    return sum(P.card_value(r) for r, _ in cards)

def handle_client(conn: socket.socket, addr, team_name: str) -> None:
    ip, port = addr[0], addr[1]
    try:
        req_bytes = read_exact(conn, P.REQUEST_STRUCT.size)
        req = P.unpack_request(req_bytes)
        if not req:
            print(f"[{ip}:{port}] Invalid request; closing.")
            return

        rounds = max(1, min(255, req.rounds))
        print(f"[{ip}:{port}] Connected client '{req.client_name}' requested {rounds} rounds.")

        for round_idx in range(1, rounds + 1):
            print(f"[{ip}:{port}] --- Round {round_idx}/{rounds} --- for '{req.client_name}'")
            deck = fresh_shuffled_deck()

            player: List[Card] = [deck.pop(), deck.pop()]
            dealer_up = deck.pop()
            dealer_down = deck.pop()
            dealer: List[Card] = [dealer_up, dealer_down]

            # Send initial deal: player 2 cards, dealer upcard
            send_update(conn, P.RES_NOT_OVER, player[0])
            send_update(conn, P.RES_NOT_OVER, player[1])
            send_update(conn, P.RES_NOT_OVER, dealer_up)

            print(f"[{ip}:{port}] Player: {P.card_str(*player[0])}, {P.card_str(*player[1])} (sum={sum_cards(player)})")
            print(f"[{ip}:{port}] Dealer shows: {P.card_str(*dealer_up)} (hidden=??)")

            # Player turn
            player_bust = False
            while True:
                decision_bytes = read_exact(conn, P.CLIENT_PAYLOAD_STRUCT.size)
                decision = P.unpack_client_decision(decision_bytes)
                if decision is None:
                    print(f"[{ip}:{port}] Invalid payload decision; closing.")
                    return

                if decision == "Stand":
                    print(f"[{ip}:{port}] Player stands (sum={sum_cards(player)}).")
                    break

                # Hittt
                new_card = deck.pop()
                player.append(new_card)
                send_update(conn, P.RES_NOT_OVER, new_card)

                p_sum = sum_cards(player)
                print(f"[{ip}:{port}] Player hits: {P.card_str(*new_card)} (sum={p_sum})")
                if p_sum > 21:
                    player_bust = True
                    print(f"[{ip}:{port}] Player busts -> dealer wins.")
                    send_update(conn, P.RES_LOSS, None)  # final result
                    break

            if player_bust:
                continue  # next round

            # Dealer turn: reveal downcard
            send_update(conn, P.RES_NOT_OVER, dealer_down)
            print(f"[{ip}:{port}] Dealer reveals: {P.card_str(*dealer_down)} (sum={sum_cards(dealer)})")

            # Dealer hits while sum < 17
            while sum_cards(dealer) < 17:
                c = deck.pop()
                dealer.append(c)
                send_update(conn, P.RES_NOT_OVER, c)
                d_sum = sum_cards(dealer)
                print(f"[{ip}:{port}] Dealer hits: {P.card_str(*c)} (sum={d_sum})")
                if d_sum > 21:
                    print(f"[{ip}:{port}] Dealer busts -> client wins.")
                    send_update(conn, P.RES_WIN, None)
                    break
            else:
                # dealer stands (sum >= 17)
                p_sum = sum_cards(player)
                d_sum = sum_cards(dealer)
                print(f"[{ip}:{port}] Dealer stands (sum={d_sum}).")

                if d_sum > 21:
                    # shouldn't happen due to loop, but keep safe
                    send_update(conn, P.RES_WIN, None)
                elif p_sum > d_sum:
                    print(f"[{ip}:{port}] Client wins {p_sum} vs {d_sum}.")
                    send_update(conn, P.RES_WIN, None)
                elif p_sum < d_sum:
                    print(f"[{ip}:{port}] Dealer wins {d_sum} vs {p_sum}.")
                    send_update(conn, P.RES_LOSS, None)
                else:
                    print(f"[{ip}:{port}] Tie {p_sum} vs {d_sum}.")
                    send_update(conn, P.RES_TIE, None)

        print(f"[{ip}:{port}] Finished all rounds; closing connection.")

    except (ConnectionError, OSError) as e:
        print(f"[{ip}:{port}] Connection error: {e}")
    finally:
        try:
            conn.close()
        except Exception:
            pass

def udp_broadcaster(stop_evt: threading.Event, udp_port: int, tcp_port: int, team_name: str) -> None:
    msg = P.pack_offer(tcp_port, team_name)
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        while not stop_evt.is_set():
            s.sendto(msg, (BROADCAST_ADDR, udp_port))
            time.sleep(1.0)
    finally:
        s.close()

def main():
    ap = argparse.ArgumentParser(description="Blackjack Dealer Server")
    ap.add_argument("--team", default="TeamServer", help="Server team name (<=32 bytes UTF-8 recommended)")
    ap.add_argument("--udp-port", type=int, default=DEFAULT_UDP_PORT, help="UDP port for offers (clients listen here)")
    ap.add_argument("--tcp-port", type=int, default=0, help="TCP port to listen on (0 = auto)")
    ap.add_argument("--bind", default="0.0.0.0", help="Bind address for TCP server (default all interfaces)")
    args = ap.parse_args()

    # TCP listening socket
    tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    tcp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    tcp.bind((args.bind, args.tcp_port))
    tcp.listen()
    actual_tcp_port = tcp.getsockname()[1]

    print(f"Server started, listening on IP address {socket.gethostbyname(socket.gethostname())} (TCP port {actual_tcp_port})")

    stop_evt = threading.Event()
    t = threading.Thread(target=udp_broadcaster, args=(stop_evt, args.udp_port, actual_tcp_port, args.team), daemon=True)
    t.start()

    try:
        while True:
            conn, addr = tcp.accept()
            th = threading.Thread(target=handle_client, args=(conn, addr, args.team), daemon=True)
            th.start()
    except KeyboardInterrupt:
        print("\nShutting down server...")
    finally:
        stop_evt.set()
        try:
            tcp.close()
        except Exception:
            pass

if __name__ == "__main__":
    main()
