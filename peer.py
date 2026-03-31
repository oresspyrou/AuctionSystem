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
#  ΠΑΡΑΓΩΓΗ ΑΝΤΙΚΕΙΜΕΝΩΝ & REQUEST AUCTION
# ─────────────────────────────────────────────

def generate_objects(peer_id: str) -> list:
    """
    Παράγει αντικείμενα σύμφωνα με την εκφώνηση:
    - Το 1ο αντικείμενο παράγεται μετά από RAND*120 sec
    - Κάθε επόμενο μετά από νέο RAND*120 sec από το προηγούμενο
    Εδώ το καλούμε χωρίς αναμονή (παράγουμε αντικείμενα άμεσα για demo).
    Η αναμονή γίνεται στο background thread generate_objects_loop.
    """
    obj_id = f"Object_{peer_id}_{int(time.time())}"
    start_bid = round(random.uniform(10, 500), 2)
    duration  = random.choice([20, 30, 45, 60])   # δευτερόλεπτα

    obj = {
        "object_id":        obj_id,
        "description":      f"Αντικείμενο {obj_id} από peer {peer_id}",
        "start_bid":        start_bid,
        "auction_duration": duration,
    }

    # Αποθήκευση στο shared_directory
    filepath = os.path.join(SHARED_DIR, f"{obj_id}.txt")
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)

    print(f"[PEER] Παράχθηκε αντικείμενο: {obj_id} | Τιμή εκκίνησης: {start_bid} | "
          f"Διάρκεια δημοπρασίας: {duration}s")
    return [obj]


def generate_objects_loop(peer_id: str, conn: socket.socket):
    """
    Background thread: παράγει αντικείμενα σε τυχαία διαστήματα (RAND*120s)
    και τα στέλνει αυτόματα στον server μέσω request_auction.
    """
    while True:
        wait_time = random.random() * 120   # RAND * 120 sec
        print(f"[PEER] Επόμενο αντικείμενο σε {wait_time:.1f}s...")
        time.sleep(wait_time)

        if token_id is None:
            continue   # δεν είμαστε logged in, παραλείπουμε

        objects = generate_objects(peer_id)
        request_auction(conn, objects)


def request_auction(conn: socket.socket, objects: list):
    """Στέλνει λίστα αντικειμένων στον server για δημοπράτηση."""
    if token_id is None:
        print("[PEER] Πρέπει να είσαι logged in για request_auction.")
        return

    send_msg(conn, {
        "action":   "request_auction",
        "token_id": token_id,
        "objects":  objects,
    })
    resp = recv_msg(conn)
    if resp:
        print(f"[PEER] RequestAuction → {resp.get('message')}")


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
        send_msg(conn, {"status": "ok", "message": "Ο peer είναι ενεργός."})

    elif action == "transaction_buy":
        handle_sell(conn, msg)

    elif action == "new_auction":
        # Ο server ανακοινώνει νέα δημοπρασία
        print(f"\n[PEER] *** ΝΕΑ ΔΗΜΟΠΡΑΣΙΑ ***")
        print(f"  Αντικείμενο: {msg.get('object_id')}")
        print(f"  Περιγραφή:   {msg.get('description')}")
        print(f"  Τιμή εκκίνησης: {msg.get('start_bid')}")
        print(f"  Διάρκεια: {msg.get('duration')}s")

    elif action == "you_won":
        print(f"\n[PEER] *** ΚΕΡΔΙΣΕΣ τη δημοπρασία! ***")
        print(f"  Αντικείμενο: {msg.get('object_id')} | Τιμή: {msg.get('winning_bid')}")
        print(f"  Πωλητής: {msg.get('seller_username')} @ {msg.get('seller_ip')}:{msg.get('seller_port')}")

    elif action == "your_item_sold":
        print(f"\n[PEER] *** Το αντικείμενό σου πουλήθηκε! ***")
        print(f"  Αντικείμενο: {msg.get('object_id')} | Τιμή: {msg.get('winning_bid')}")
        print(f"  Αγοραστής: {msg.get('buyer_username')}")

    elif action == "auction_ended":
        result = msg.get("result")
        if result == "no_bids":
            print(f"\n[PEER] Δημοπρασία {msg.get('object_id')} έληξε χωρίς προσφορά.")
        else:
            print(f"\n[PEER] Δημοπρασία {msg.get('object_id')} ολοκληρώθηκε. "
                  f"Τιμή πώλησης: {msg.get('winning_bid')}")

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

    # Μοναδικό ID για αυτό το peer instance (για ονομασία αντικειμένων)
    peer_id = str(random.randint(1000, 9999))
    print(f"[PEER] Peer ID: {peer_id} | Port: {PEER_PORT}")

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
        print("4. Δημιούργησε & στείλε αντικείμενο τώρα (manual)")
        print("5. Εκκίνηση αυτόματης παραγωγής αντικειμένων (RAND×120s)")
        print("0. Έξοδος")
        choice = input("Επιλογή: ").strip()

        if choice == "1":
            register(server_conn)
        elif choice == "2":
            if login(server_conn):
                # Αμέσως μετά το login στέλνουμε τα αντικείμενα που ήδη υπάρχουν
                existing = []
                for fname in os.listdir(SHARED_DIR):
                    if fname.endswith(".txt"):
                        with open(os.path.join(SHARED_DIR, fname), 'r', encoding='utf-8') as f:
                            try:
                                existing.append(json.load(f))
                            except Exception:
                                pass
                if existing:
                    print(f"[PEER] Βρέθηκαν {len(existing)} αντικείμενα στο shared_dir — στέλνονται στον server.")
                    request_auction(server_conn, existing)
        elif choice == "3":
            if token_id:
                logout(server_conn)
            else:
                print("[PEER] Δεν είσαι συνδεδεμένος.")
        elif choice == "4":
            if token_id:
                objects = generate_objects(peer_id)
                request_auction(server_conn, objects)
            else:
                print("[PEER] Κάνε login πρώτα.")
        elif choice == "5":
            if token_id:
                t_gen = threading.Thread(
                    target=generate_objects_loop,
                    args=(peer_id, server_conn),
                    daemon=True
                )
                t_gen.start()
                print("[PEER] Αυτόματη παραγωγή αντικειμένων ενεργοποιήθηκε.")
            else:
                print("[PEER] Κάνε login πρώτα.")
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
