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
#  ΚΥΡΙΟΣ SERVER LOOP
# ─────────────────────────────────────────────

def start_server():
    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_sock.bind((HOST, PORT))
    server_sock.listen(10)
    print(f"[SERVER] Ακούει στο {HOST}:{PORT} ...")

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
