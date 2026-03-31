import socket
import threading
import json
import random
import time
import os

# ─────────────────────────────────────────────
#  ΣΤΑΘΕΡΕΣ
# ─────────────────────────────────────────────
SERVER_HOST = '127.0.0.1'
SERVER_PORT = 5000
BUFFER = 4096

# Ο peer επιλέγει τυχαία θύρα για το δικό του server socket
PEER_HOST = '127.0.0.1'
PEER_PORT = random.randint(6000, 9000)

SHARED_DIR = "shared_directory"   # τοπικός φάκελος αντικειμένων


# ─────────────────────────────────────────────
#  ΚΑΤΑΣΤΑΣΗ PEER
# ─────────────────────────────────────────────
token_id = None          # μετά το login
server_conn = None       # socket προς Auction Server


# ─────────────────────────────────────────────
#  ΒΟΗΘΗΤΙΚΕΣ ΣΥΝΑΡΤΗΣΕΙΣ
# ─────────────────────────────────────────────

def send_msg(conn, data: dict):
    """Στέλνει dict ως JSON string με newline terminator."""
    try:
        msg = json.dumps(data) + "\n"
        conn.sendall(msg.encode('utf-8'))
    except Exception as e:
        print(f"[PEER] send_msg error: {e}")


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
        print(f"[PEER] recv_msg error: {e}")
        return None


def connect_to_server() -> socket.socket:
    """Δημιουργεί σύνδεση με τον Auction Server."""
    conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    conn.connect((SERVER_HOST, SERVER_PORT))
    return conn


def ensure_shared_dir():
    """Δημιουργεί τον shared_directory αν δεν υπάρχει."""
    if not os.path.exists(SHARED_DIR):
        os.makedirs(SHARED_DIR)
        print(f"[PEER] Δημιουργήθηκε φάκελος: {SHARED_DIR}/")


# ─────────────────────────────────────────────
#  ΛΕΙΤΟΥΡΓΙΕΣ AUTH
# ─────────────────────────────────────────────

def register(conn):
    username = input("  Username: ").strip()
    password = input("  Password: ").strip()
    send_msg(conn, {"action": "register", "username": username, "password": password})
    resp = recv_msg(conn)
    print(f"[PEER] Register → {resp.get('message')}")
    return resp.get("status") == "ok"


def login(conn):
    global token_id
    username = input("  Username: ").strip()
    password = input("  Password: ").strip()
    send_msg(conn, {
        "action": "login",
        "username": username,
        "password": password,
        "peer_port": PEER_PORT
    })
    resp = recv_msg(conn)
    print(f"[PEER] Login → {resp.get('message')}")
    if resp.get("status") == "ok":
        token_id = resp.get("token_id")
        print(f"[PEER] Token: {token_id}")
        return True
    return False


def logout(conn):
    global token_id
    send_msg(conn, {"action": "logout", "token_id": token_id})
    resp = recv_msg(conn)
    print(f"[PEER] Logout → {resp.get('message')}")
    token_id = None


# ─────────────────────────────────────────────
#  SERVER SOCKET ΤΟΥ PEER
#  (ακούει για peer-to-peer συνδέσεις & check_active)
# ─────────────────────────────────────────────

def peer_server_loop():
    """Τρέχει σε ξεχωριστό thread — ακούει για εισερχόμενες συνδέσεις."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((PEER_HOST, PEER_PORT))
    srv.listen(5)
    print(f"[PEER] Peer server ακούει στο {PEER_HOST}:{PEER_PORT}")

    while True:
        try:
            conn, addr = srv.accept()
            t = threading.Thread(target=handle_incoming, args=(conn, addr), daemon=True)
            t.start()
        except Exception as e:
            print(f"[PEER] Peer server error: {e}")
            break


def handle_incoming(conn, addr):
    """Χειρίζεται εισερχόμενη σύνδεση από άλλο peer ή server."""
    msg = recv_msg(conn)
    if msg is None:
        conn.close()
        return

    action = msg.get("action")
    print(f"[PEER] Εισερχόμενο action='{action}' από {addr}")

    if action == "check_active":
        # Ο server ελέγχει αν είμαστε online
        send_msg(conn, {"status": "ok", "message": "Ο peer είναι ενεργός."})

    elif action == "transaction_buy":
        # Κάποιος αγοραστής ζητά το αρχείο metadata (ρόλος πωλητή)
        handle_sell(conn, msg)

    elif action == "auction_result":
        # Ο server μας ενημερώνει ότι κερδίσαμε δημοπρασία (ρόλος αγοραστή)
        print(f"[PEER] 🎉 Κερδίσαμε δημοπρασία! {msg}")

    conn.close()


def handle_sell(conn, msg):
    """Στέλνει το αρχείο metadata στον αγοραστή."""
    object_id = msg.get("object_id")
    filepath = os.path.join(SHARED_DIR, f"{object_id}.txt")

    if not os.path.exists(filepath):
        send_msg(conn, {"status": "error", "message": "Αρχείο δεν βρέθηκε."})
        return

    with open(filepath, 'r') as f:
        content = f.read()

    send_msg(conn, {"status": "ok", "object_id": object_id, "metadata": content})
    os.remove(filepath)
    print(f"[PEER] Στάλθηκε και διαγράφηκε το αρχείο {object_id}.txt")


# ─────────────────────────────────────────────
#  ΚΥΡΙΟ ΜΕΝΟΥ
# ─────────────────────────────────────────────

def main():
    global server_conn
    ensure_shared_dir()

    # Εκκίνηση peer server σε background thread
    t = threading.Thread(target=peer_server_loop, daemon=True)
    t.start()

    # Σύνδεση στον Auction Server
    server_conn = connect_to_server()
    print(f"[PEER] Συνδέθηκε στον Auction Server {SERVER_HOST}:{SERVER_PORT}")

    while True:
        print("\n=== ΜΕΝΟΥ PEER ===")
        print("1. Register")
        print("2. Login")
        print("3. Logout")
        print("0. Έξοδος")
        choice = input("Επιλογή: ").strip()

        if choice == "1":
            register(server_conn)
        elif choice == "2":
            login(server_conn)
        elif choice == "3":
            if token_id:
                logout(server_conn)
            else:
                print("[PEER] Δεν είσαι συνδεδεμένος.")
        elif choice == "0":
            if token_id:
                logout(server_conn)
            server_conn.close()
            print("[PEER] Αποσύνδεση.")
            break
        else:
            print("Μη έγκυρη επιλογή.")


if __name__ == "__main__":
    main()
