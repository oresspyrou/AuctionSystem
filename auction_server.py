import socket
import threading
import json
import random
import time

# ─────────────────────────────────────────────
#  ΣΤΑΘΕΡΕΣ
# ─────────────────────────────────────────────
HOST = '127.0.0.1'   # localhost – τρέχουμε όλα στο ίδιο μηχάνημα
PORT = 5000           # η μόνη γνωστή εκ των προτέρων θύρα (server)
BUFFER = 4096         # μέγεθος buffer για recv()

# ─────────────────────────────────────────────
#  ΚΟΙΝΕΣ ΔΟΜΕΣ ΔΕΔΟΜΕΝΩΝ  (προστατεύονται από Lock)
# ─────────────────────────────────────────────
lock = threading.Lock()

# { username -> {"password": ..., "num_auctions_seller": 0, "num_auctions_bidder": 0} }
registered_users = {}

# { token_id -> {"username": ..., "ip": ..., "port": ..., "conn": <socket>} }
active_sessions = {}

# Ουρά αντικειμένων προς δημοπράτηση (FCFS)
# Κάθε στοιχείο: {"token_id": ..., "object_id": ..., "description": ...,
#                  "start_bid": ..., "auction_duration": ...}
auction_queue = []

# Τρέχουσα δημοπρασία
# { "object_id", "description", "start_bid", "current_bid",
#   "highest_bidder_token", "seller_token", "end_time" }
current_auction = None

# Condition για να ξυπνάει το auction thread όταν μπει νέο αντικείμενο στην ουρά
auction_queue_condition = threading.Condition(lock)


# ─────────────────────────────────────────────
#  ΒΟΗΘΗΤΙΚΕΣ ΣΥΝΑΡΤΗΣΕΙΣ
# ─────────────────────────────────────────────

def send_msg(conn, data: dict):
    """Στέλνει dict ως JSON string με newline terminator."""
    try:
        msg = json.dumps(data) + "\n"
        conn.sendall(msg.encode('utf-8'))
    except Exception as e:
        print(f"[SERVER] send_msg error: {e}")


def recv_msg(conn) -> dict | None:
    """Λαμβάνει ένα JSON μήνυμα από το socket."""
    try:
        data = b""
        while not data.endswith(b"\n"):
            chunk = conn.recv(BUFFER)
            if not chunk:
                return None
            data += chunk
        return json.loads(data.decode('utf-8').strip())
    except Exception as e:
        print(f"[SERVER] recv_msg error: {e}")
        return None


def generate_token() -> str:
    """Παράγει τυχαίο token_id για session."""
    return str(random.randint(100000, 999999))


# ─────────────────────────────────────────────
#  ΧΕΙΡΙΣΜΟΣ ΚΆΘΕ PEER (τρέχει σε ξεχωριστό thread)
# ─────────────────────────────────────────────

def handle_peer(conn, addr):
    print(f"[SERVER] Νέα σύνδεση από {addr}")
    try:
        while True:
            msg = recv_msg(conn)
            if msg is None:
                print(f"[SERVER] Ο peer {addr} αποσυνδέθηκε.")
                break

            action = msg.get("action")
            print(f"[SERVER] Λήφθηκε action='{action}' από {addr}")

            if action == "register":
                handle_register(conn, msg)
            elif action == "login":
                handle_login(conn, msg, addr)
            elif action == "logout":
                handle_logout(conn, msg)
            elif action == "request_auction":
                handle_request_auction(conn, msg)
            else:
                send_msg(conn, {"status": "error", "message": f"Άγνωστη action: {action}"})

    except Exception as e:
        print(f"[SERVER] Σφάλμα στο handle_peer {addr}: {e}")
    finally:
        conn.close()


# ─────────────────────────────────────────────
#  ΛΕΙΤΟΥΡΓΙΕΣ AUTH
# ─────────────────────────────────────────────

def handle_register(conn, msg):
    username = msg.get("username", "").strip()
    password = msg.get("password", "").strip()

    if not username or not password:
        send_msg(conn, {"status": "error", "message": "Username/password δεν μπορούν να είναι κενά."})
        return

    with lock:
        if username in registered_users:
            send_msg(conn, {"status": "error", "message": "Το username χρησιμοποιείται ήδη."})
        else:
            registered_users[username] = {
                "password": password,
                "num_auctions_seller": 0,
                "num_auctions_bidder": 0
            }
            print(f"[SERVER] Νέος χρήστης εγγράφηκε: {username}")
            send_msg(conn, {"status": "ok", "message": f"Εγγραφή επιτυχής για '{username}'."})


def handle_login(conn, msg, addr):
    username = msg.get("username", "").strip()
    password = msg.get("password", "").strip()
    peer_port = msg.get("peer_port")   # θύρα του server socket του peer

    with lock:
        user = registered_users.get(username)
        if user is None or user["password"] != password:
            send_msg(conn, {"status": "error", "message": "Λάθος username ή password."})
            return

        token = generate_token()
        active_sessions[token] = {
            "username": username,
            "ip": addr[0],
            "port": peer_port,
            "conn": conn
        }
        print(f"[SERVER] Login: {username} | token={token}")
        send_msg(conn, {"status": "ok", "token_id": token, "message": "Login επιτυχής."})


def handle_logout(conn, msg):
    token = msg.get("token_id", "")

    with lock:
        session = active_sessions.pop(token, None)

    if session is None:
        send_msg(conn, {"status": "error", "message": "Άγνωστο token_id."})
    else:
        print(f"[SERVER] Logout: {session['username']}")
        send_msg(conn, {"status": "ok", "message": "Logout επιτυχής."})


# ─────────────────────────────────────────────
#  ΛΕΙΤΟΥΡΓΙΕΣ ΔΗΜΟΠΡΑΣΙΑΣ
# ─────────────────────────────────────────────

def handle_request_auction(conn, msg):
    """Ο peer στέλνει τα αντικείμενά του προς δημοπράτηση (μετά το login)."""
    token = msg.get("token_id", "")
    objects = msg.get("objects", [])   # λίστα από dicts με metadata

    with auction_queue_condition:
        session = active_sessions.get(token)
        if session is None:
            send_msg(conn, {"status": "error", "message": "Μη έγκυρο token_id."})
            return

        username = session["username"]
        added = 0
        for obj in objects:
            # Προσθέτουμε το token_id του πωλητή σε κάθε αντικείμενο
            obj["seller_token"] = token
            obj["seller_username"] = username
            auction_queue.append(obj)
            added += 1

        print(f"[SERVER] {username} πρόσθεσε {added} αντικείμενα στην ουρά. "
              f"Συνολικά στην ουρά: {len(auction_queue)}")

        # Ξυπνάμε το auction_loop αν περιμένει για νέο αντικείμενο
        auction_queue_condition.notify_all()

    send_msg(conn, {
        "status": "ok",
        "message": f"{added} αντικείμενα προστέθηκαν στην ουρά."
    })


def broadcast_to_active_peers(msg: dict, exclude_token: str = None):
    """Στέλνει μήνυμα σε όλους τους ενεργούς peers (εκτός από τον exclude_token)."""
    with lock:
        sessions_snapshot = dict(active_sessions)

    for token, session in sessions_snapshot.items():
        if token == exclude_token:
            continue
        try:
            send_msg(session["conn"], msg)
        except Exception as e:
            print(f"[SERVER] Αδυναμία αποστολής στον {session['username']}: {e}")


def auction_loop():
    """
    Τρέχει σε ξεχωριστό thread.
    Επιλέγει αντικείμενα από την ουρά (FCFS) και διεξάγει μία δημοπρασία κάθε φορά.
    """
    global current_auction

    print("[SERVER] Auction loop ξεκίνησε.")

    while True:
        # ── Αναμονή για αντικείμενο στην ουρά ──
        with auction_queue_condition:
            while len(auction_queue) == 0:
                print("[SERVER] Ουρά κενή — αναμονή για νέο αντικείμενο...")
                auction_queue_condition.wait()

            # Παίρνουμε το πρώτο αντικείμενο (FCFS)
            item = auction_queue.pop(0)

        duration = float(item.get("auction_duration", 30))  # δευτερόλεπτα
        end_time = time.time() + duration

        with lock:
            current_auction = {
                "object_id":           item["object_id"],
                "description":         item.get("description", ""),
                "start_bid":           float(item.get("start_bid", 0)),
                "current_bid":         float(item.get("start_bid", 0)),
                "highest_bidder_token": None,
                "seller_token":        item["seller_token"],
                "seller_username":     item["seller_username"],
                "end_time":            end_time,
            }

        print(f"[SERVER] *** Νέα δημοπρασία: {item['object_id']} | "
              f"Τιμή εκκίνησης: {item['start_bid']} | "
              f"Διάρκεια: {duration}s ***")

        # Ενημερώνουμε όλους τους peers για τη νέα δημοπρασία
        broadcast_to_active_peers({
            "action":      "new_auction",
            "object_id":   current_auction["object_id"],
            "description": current_auction["description"],
            "start_bid":   current_auction["start_bid"],
            "duration":    duration,
        })

        # ── Αναμονή μέχρι τη λήξη της δημοπρασίας ──
        time.sleep(duration)

        # ── Ανακοίνωση αποτελέσματος ──
        with lock:
            auction = current_auction
            current_auction = None

        if auction["highest_bidder_token"] is None:
            print(f"[SERVER] Δημοπρασία {auction['object_id']} έληξε χωρίς προσφορά.")
            broadcast_to_active_peers({
                "action":    "auction_ended",
                "object_id": auction["object_id"],
                "result":    "no_bids",
            })
        else:
            winner_token = auction["highest_bidder_token"]
            seller_token = auction["seller_token"]
            winning_bid  = auction["current_bid"]

            print(f"[SERVER] Νικητής: token={winner_token} | "
                  f"Τιμή: {winning_bid} | Αντικείμενο: {auction['object_id']}")

            # Ενημέρωση νικητή
            with lock:
                winner_session = active_sessions.get(winner_token)
                seller_session = active_sessions.get(seller_token)
                # Ενημέρωση μετρητών
                if winner_session:
                    registered_users[winner_session["username"]]["num_auctions_bidder"] += 1
                if seller_session:
                    registered_users[seller_session["username"]]["num_auctions_seller"] += 1

            if winner_session:
                send_msg(winner_session["conn"], {
                    "action":         "you_won",
                    "object_id":      auction["object_id"],
                    "winning_bid":    winning_bid,
                    "seller_ip":      seller_session["ip"]   if seller_session else None,
                    "seller_port":    seller_session["port"] if seller_session else None,
                    "seller_username": auction["seller_username"],
                })

            if seller_session:
                send_msg(seller_session["conn"], {
                    "action":          "your_item_sold",
                    "object_id":       auction["object_id"],
                    "winning_bid":     winning_bid,
                    "buyer_username":  winner_session["username"] if winner_session else "άγνωστος",
                })

            # Broadcast αποτελέσματος σε όλους
            broadcast_to_active_peers({
                "action":    "auction_ended",
                "object_id": auction["object_id"],
                "result":    "sold",
                "winning_bid": winning_bid,
            }, exclude_token=winner_token)


# ─────────────────────────────────────────────
#  ΚΥΡΙΟΣ SERVER LOOP
# ─────────────────────────────────────────────

def start_server():
    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_sock.bind((HOST, PORT))
    server_sock.listen(10)
    print(f"[SERVER] Ακούει στο {HOST}:{PORT} ...")

    # Εκκίνηση auction loop σε background thread
    t_auction = threading.Thread(target=auction_loop, daemon=True)
    t_auction.start()

    try:
        while True:
            conn, addr = server_sock.accept()
            t = threading.Thread(target=handle_peer, args=(conn, addr), daemon=True)
            t.start()
    except KeyboardInterrupt:
        print("\n[SERVER] Τερματισμός.")
    finally:
        server_sock.close()


if __name__ == "__main__":
    start_server()
