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
peer_username = None     # username μετά το login
server_conn = None       # socket προς Auction Server

# Lock για thread-safe αποστολή στον server (menu thread + listener thread)
send_lock = threading.Lock()


# ─────────────────────────────────────────────
#  ΒΟΗΘΗΤΙΚΕΣ ΣΥΝΑΡΤΗΣΕΙΣ
# ─────────────────────────────────────────────

def send_msg(conn, data: dict):
    """Στέλνει dict ως JSON string με newline terminator (thread-safe)."""
    try:
        msg = json.dumps(data) + "\n"
        with send_lock:
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
    global token_id, peer_username
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
        token_id     = resp.get("token_id")
        peer_username = username
        print(f"[PEER] Token: {token_id}")
        return True
    return False


def logout(conn):
    global token_id, peer_username
    send_msg(conn, {"action": "logout", "token_id": token_id})
    resp = recv_msg(conn)
    print(f"[PEER] Logout → {resp.get('message')}")
    token_id     = None
    peer_username = None


# ─────────────────────────────────────────────
#  ASYNC LISTENER — διαβάζει inbound μηνύματα
#  από τον server σε background thread
# ─────────────────────────────────────────────

def server_listener(conn: socket.socket):
    """
    Τρέχει σε background thread.
    Διαβάζει ό,τι στέλνει ο server ασύγχρονα (push μηνύματα:
    new_auction, bid_update, you_won, your_item_sold, auction_ended).
    ΔΕΝ διαβάζει τις απαντήσεις σε request/response — αυτές τις
    διαβάζει το κύριο thread αμέσως μετά από κάθε send_msg.
    """
    while True:
        msg = recv_msg(conn)
        if msg is None:
            print("[PEER] Χάθηκε σύνδεση με τον server.")
            break

        action = msg.get("action")

        if action == "new_auction":
            print(f"\n\n[PEER] *** ΝΕΑ ΔΗΜΟΠΡΑΣΙΑ ***")
            print(f"  Αντικείμενο : {msg.get('object_id')}")
            print(f"  Περιγραφή   : {msg.get('description')}")
            print(f"  Τιμή εκκίνησης: {msg.get('start_bid')}")
            print(f"  Διάρκεια    : {msg.get('duration')}s")
            print("Επιλογή: ", end="", flush=True)

        elif action == "bid_update":
            print(f"\n[PEER] Νέα προσφορά: {msg.get('new_bid')} "
                  f"από {msg.get('bidder')} για {msg.get('object_id')}")
            print("Επιλογή: ", end="", flush=True)

        elif action == "you_won":
            print(f"\n[PEER] *** ΚΕΡΔΙΣΕΣ τη δημοπρασία! ***")
            print(f"  Αντικείμενο : {msg.get('object_id')} | Τιμή: {msg.get('winning_bid')}")
            print(f"  Πωλητής     : {msg.get('seller_username')} "
                  f"@ {msg.get('seller_ip')}:{msg.get('seller_port')}")
            print("Επιλογή: ", end="", flush=True)

        elif action == "your_item_sold":
            print(f"\n[PEER] *** Το αντικείμενό σου πουλήθηκε! ***")
            print(f"  Αντικείμενο : {msg.get('object_id')} | Τιμή: {msg.get('winning_bid')}")
            print(f"  Αγοραστής   : {msg.get('buyer_username')}")
            print("Επιλογή: ", end="", flush=True)

        elif action == "auction_ended":
            if msg.get("result") == "no_bids":
                print(f"\n[PEER] Δημοπρασία {msg.get('object_id')} έληξε χωρίς προσφορά.")
            else:
                print(f"\n[PEER] Δημοπρασία {msg.get('object_id')} ολοκληρώθηκε. "
                      f"Τιμή: {msg.get('winning_bid')}")
            print("Επιλογή: ", end="", flush=True)


# ─────────────────────────────────────────────
#  ΛΕΙΤΟΥΡΓΙΕΣ ΔΗΜΟΠΡΑΣΙΑΣ (peer → server)
# ─────────────────────────────────────────────

def get_current_auction(conn: socket.socket):
    """Ρωτά τον server ποιο αντικείμενο δημοπρατείται τώρα."""
    send_msg(conn, {"action": "get_current_auction", "token_id": token_id})
    resp = recv_msg(conn)
    if resp and resp.get("active"):
        print(f"[PEER] Τρέχουσα δημοπρασία: {resp.get('object_id')} — {resp.get('description')}")
    else:
        print(f"[PEER] {resp.get('message') if resp else 'Δεν υπάρχει απόκριση.'}")


def get_auction_details(conn: socket.socket):
    """Ζητά λεπτομέρειες για την τρέχουσα δημοπρασία."""
    send_msg(conn, {"action": "get_auction_details", "token_id": token_id})
    resp = recv_msg(conn)
    if resp and resp.get("active"):
        print(f"[PEER] Λεπτομέρειες δημοπρασίας:")
        print(f"  Αντικείμενο   : {resp.get('object_id')}")
        print(f"  Περιγραφή     : {resp.get('description')}")
        print(f"  Τρέχουσα τιμή : {resp.get('current_bid')}")
        print(f"  Πωλητής       : {resp.get('seller_username')}")
        print(f"  Χρόνος που απομένει: {resp.get('time_remaining')}s")
        return resp
    else:
        print(f"[PEER] {resp.get('message') if resp else 'Δεν υπάρχει απόκριση.'}")
        return None


def place_bid(conn: socket.socket):
    """Κάνει νέα προσφορά για την τρέχουσα δημοπρασία."""
    # Πρώτα παίρνουμε τις λεπτομέρειες για να υπολογίσουμε το NewBid
    details = get_auction_details(conn)
    if details is None:
        return

    current_bid   = float(details.get("current_bid", 0))
    seller_token  = details.get("seller_token")
    object_id     = details.get("object_id")

    # Έλεγχος ενδιαφέροντος: 60% πιθανότητα (εκφώνηση)
    interested = random.random() < 0.60
    print(f"[PEER] Ενδιαφέρον για αγορά; {'ΝΑΙ' if interested else 'ΟΧΙ'}")
    if not interested:
        return

    # Υπολογισμός νέας προσφοράς: NewBid = HighestBid * (1 + RAND/10)
    new_bid = round(current_bid * (1 + random.random() / 10), 2)
    print(f"[PEER] Στέλνω προσφορά: {new_bid} για {object_id}")

    send_msg(conn, {
        "action":    "place_bid",
        "token_id":  token_id,
        "object_id": object_id,
        "bid":       new_bid,
    })
    resp = recv_msg(conn)
    if resp:
        print(f"[PEER] PlaceBid → {resp.get('message')}")


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

    # Τα υπόλοιπα push μηνύματα (new_auction, bid_update, κτλ.)
    # τα χειρίζεται ο server_listener thread — όχι εδώ.

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

    peer_id = str(random.randint(1000, 9999))
    print(f"[PEER] Peer ID: {peer_id} | Port: {PEER_PORT}")

    # Εκκίνηση peer server σε background thread
    threading.Thread(target=peer_server_loop, daemon=True).start()

    # Σύνδεση στον Auction Server
    server_conn = connect_to_server()
    print(f"[PEER] Συνδέθηκε στον Auction Server {SERVER_HOST}:{SERVER_PORT}")

    # Εκκίνηση async listener για push μηνύματα από τον server
    threading.Thread(target=server_listener, args=(server_conn,), daemon=True).start()

    while True:
        print("\n=== ΜΕΝΟΥ PEER ===")
        print("1. Register")
        print("2. Login")
        print("3. Logout")
        print("4. Δες τρέχουσα δημοπρασία")
        print("5. Δες λεπτομέρειες δημοπρασίας")
        print("6. Κάνε προσφορά (place bid)")
        print("7. Δημιούργησε & στείλε αντικείμενο τώρα (manual)")
        print("8. Εκκίνηση αυτόματης παραγωγής αντικειμένων (RAND×120s)")
        print("0. Έξοδος")
        choice = input("Επιλογή: ").strip()

        if choice == "1":
            register(server_conn)
        elif choice == "2":
            if login(server_conn):
                existing = []
                for fname in os.listdir(SHARED_DIR):
                    if fname.endswith(".txt"):
                        with open(os.path.join(SHARED_DIR, fname), 'r', encoding='utf-8') as f:
                            try:
                                existing.append(json.load(f))
                            except Exception:
                                pass
                if existing:
                    print(f"[PEER] Βρέθηκαν {len(existing)} αντικείμενα — στέλνονται στον server.")
                    request_auction(server_conn, existing)
        elif choice == "3":
            if token_id:
                logout(server_conn)
            else:
                print("[PEER] Δεν είσαι συνδεδεμένος.")
        elif choice == "4":
            if token_id:
                get_current_auction(server_conn)
            else:
                print("[PEER] Κάνε login πρώτα.")
        elif choice == "5":
            if token_id:
                get_auction_details(server_conn)
            else:
                print("[PEER] Κάνε login πρώτα.")
        elif choice == "6":
            if token_id:
                place_bid(server_conn)
            else:
                print("[PEER] Κάνε login πρώτα.")
        elif choice == "7":
            if token_id:
                objects = generate_objects(peer_id)
                request_auction(server_conn, objects)
            else:
                print("[PEER] Κάνε login πρώτα.")
        elif choice == "8":
            if token_id:
                threading.Thread(
                    target=generate_objects_loop,
                    args=(peer_id, server_conn),
                    daemon=True
                ).start()
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
