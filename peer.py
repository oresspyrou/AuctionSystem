import socket
import threading
import json
import random
import time
import os
import queue

# ─────────────────────────────────────────────
#  ΣΤΑΘΕΡΕΣ
# ─────────────────────────────────────────────
SERVER_HOST = '127.0.0.1'
SERVER_PORT = 5000
BUFFER = 4096

PEER_HOST = '127.0.0.1'
PEER_PORT = random.randint(6000, 9000)

SHARED_DIR = "shared_directory"


# ─────────────────────────────────────────────
#  ΚΑΤΑΣΤΑΣΗ PEER
# ─────────────────────────────────────────────
token_id       = None
peer_username  = None
server_conn    = None

send_lock      = threading.Lock()   # προστατεύει το sendall
request_lock   = threading.Lock()   # εξασφαλίζει ένα request τη φορά
response_queue = queue.Queue()      # απαντήσεις από τον server
polling_started = False             # για να μην ξεκινήσουμε δύο φορές το polling


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


def send_request(conn: socket.socket, data: dict) -> dict | None:
    """
    Thread-safe αποστολή request και αναμονή για απάντηση μέσω response_queue.
    Μόνο ένα request μπορεί να είναι in-flight κάθε φορά — αποτρέπει race condition
    μεταξύ main thread και background threads που χρησιμοποιούν το ίδιο socket.
    """
    with request_lock:
        send_msg(conn, data)
        try:
            return response_queue.get(timeout=10)
        except queue.Empty:
            print("[PEER] Timeout: δεν ήρθε απάντηση από τον server.")
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
    resp = send_request(conn, {"action": "register", "username": username, "password": password})
    print(f"[PEER] Register → {resp.get('message') if resp else 'Χωρίς απόκριση'}")
    return resp.get("status") == "ok" if resp else False


def login(conn):
    global token_id, peer_username, polling_started
    username = input("  Username: ").strip()
    password = input("  Password: ").strip()
    resp = send_request(conn, {
        "action":    "login",
        "username":  username,
        "password":  password,
        "peer_port": PEER_PORT,
    })
    print(f"[PEER] Login → {resp.get('message') if resp else 'Χωρίς απόκριση'}")
    if resp and resp.get("status") == "ok":
        token_id      = resp.get("token_id")
        peer_username = username
        print(f"[PEER] Token: {token_id}")
        # Εκκίνηση αυτόματου polling μόνο μία φορά
        if not polling_started:
            threading.Thread(target=auction_polling_loop, args=(conn,), daemon=True).start()
            polling_started = True
        return True
    return False


def logout(conn):
    global token_id, peer_username
    resp = send_request(conn, {"action": "logout", "token_id": token_id})
    print(f"[PEER] Logout → {resp.get('message') if resp else 'Χωρίς απόκριση'}")
    token_id      = None
    peer_username = None


# ─────────────────────────────────────────────
#  ASYNC LISTENER — διαβάζει ΟΛΑ τα inbound μηνύματα
# ─────────────────────────────────────────────

def server_listener(conn: socket.socket):
    """
    Τρέχει σε background thread και είναι ο ΜΟΝΟΣ που καλεί recv_msg(server_conn).
    - Μηνύματα χωρίς "action" (responses): προωθούνται στο response_queue
    - Μηνύματα με "action" (push): χειρίζονται άμεσα εδώ
    Έτσι εξαλείφεται το race condition μεταξύ listener και main thread.
    """
    while True:
        msg = recv_msg(conn)
        if msg is None:
            print("[PEER] Χάθηκε σύνδεση με τον server.")
            break

        action = msg.get("action")

        if action is None:
            # Απάντηση σε request — προωθούμε στον αναμένοντα thread
            response_queue.put(msg)

        elif action == "new_auction":
            print(f"\n[PEER] *** ΝΕΑ ΔΗΜΟΠΡΑΣΙΑ ***")
            print(f"  Αντικείμενο : {msg.get('object_id')}")
            print(f"  Περιγραφή   : {msg.get('description')}")
            print(f"  Τιμή εκκίνησης: {msg.get('start_bid')}")
            print(f"  Διάρκεια    : {msg.get('duration')}s")
            print("Επιλογή: ", end="", flush=True)

        elif action == "bid_update":
            print(f"\n[PEER] Νέα προσφορά: {msg.get('new_bid')} "
                  f"από {msg.get('bidder')} για {msg.get('object_id')}")
            print("Επιλογή: ", end="", flush=True)

        elif action == "auction_cancelled":
            print(f"\n[PEER] *** Δημοπρασία {msg.get('object_id')} ΑΚΥΡΩΘΗΚΕ ***")
            print(f"  Λόγος: {msg.get('reason')}")
            print("Επιλογή: ", end="", flush=True)

        elif action == "you_won":
            print(f"\n[PEER] *** ΚΕΡΔΙΣΕΣ τη δημοπρασία! ***")
            print(f"  Αντικείμενο : {msg.get('object_id')} | Τιμή: {msg.get('winning_bid')}")
            print(f"  Πωλητής     : {msg.get('seller_username')} "
                  f"@ {msg.get('seller_ip')}:{msg.get('seller_port')}")
            # Transaction σε ξεχωριστό thread για να μην μπλοκάρει τον listener
            threading.Thread(target=do_transaction, args=(msg,), daemon=True).start()
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
    resp = send_request(conn, {"action": "get_current_auction", "token_id": token_id})
    if resp and resp.get("active"):
        print(f"[PEER] Τρέχουσα δημοπρασία: {resp.get('object_id')} — {resp.get('description')}")
    else:
        print(f"[PEER] {resp.get('message') if resp else 'Δεν υπάρχει απόκριση.'}")


def get_auction_details(conn: socket.socket):
    """Ζητά λεπτομέρειες για την τρέχουσα δημοπρασία."""
    resp = send_request(conn, {"action": "get_auction_details", "token_id": token_id})
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
    """Κάνει νέα προσφορά για την τρέχουσα δημοπρασία (manual από μενού)."""
    details = get_auction_details(conn)
    if details is None:
        return

    current_bid = float(details.get("current_bid", 0))
    object_id   = details.get("object_id")

    # 60% ενδιαφέρον (εκφώνηση)
    interested = random.random() < 0.60
    print(f"[PEER] Ενδιαφέρον για αγορά; {'ΝΑΙ' if interested else 'ΟΧΙ'}")
    if not interested:
        return

    # NewBid = HighestBid * (1 + RAND/10)
    new_bid = round(current_bid * (1 + random.random() / 10), 2)
    print(f"[PEER] Στέλνω προσφορά: {new_bid} για {object_id}")

    resp = send_request(conn, {
        "action":    "place_bid",
        "token_id":  token_id,
        "object_id": object_id,
        "bid":       new_bid,
    })
    if resp:
        print(f"[PEER] PlaceBid → {resp.get('message')}")


# ─────────────────────────────────────────────
#  ΑΥΤΟΜΑΤΟ POLLING — getCurrentAuction κάθε 60s
#  Υλοποιεί τη ροή της εκφώνησης:
#  getCurrentAuction → (60%) getAuctionDetails → placeBid
# ─────────────────────────────────────────────

def auction_polling_loop(conn: socket.socket):
    """
    Background thread: κάθε 60s ρωτά για τρέχουσα δημοπρασία.
    Αν υπάρχει, με 60% πιθανότητα ζητά λεπτομέρειες και κάνει αυτόματη προσφορά.
    """
    while True:
        time.sleep(60)
        if token_id is None:
            continue

        # Βήμα 1: getCurrentAuction
        resp = send_request(conn, {"action": "get_current_auction", "token_id": token_id})
        if not resp or not resp.get("active"):
            continue

        print(f"\n[PEER] [Auto] Τρέχουσα δημοπρασία: "
              f"{resp.get('object_id')} — {resp.get('description')}")

        # Βήμα 2: coin flip 60% ενδιαφέρον
        if random.random() >= 0.60:
            print("[PEER] [Auto] Δεν ενδιαφέρομαι για αυτή τη δημοπρασία.")
            print("Επιλογή: ", end="", flush=True)
            continue

        print("[PEER] [Auto] Ενδιαφέρομαι! Ζητώ λεπτομέρειες...")

        # Βήμα 3: getAuctionDetails
        details = send_request(conn, {"action": "get_auction_details", "token_id": token_id})
        if not details or not details.get("active"):
            continue

        print(f"[PEER] [Auto] Τιμή: {details.get('current_bid')} | "
              f"Χρόνος: {details.get('time_remaining')}s")

        # Βήμα 4: placeBid — NewBid = HighestBid * (1 + RAND/10)
        current_bid = float(details.get("current_bid", 0))
        new_bid     = round(current_bid * (1 + random.random() / 10), 2)
        object_id   = details.get("object_id")

        print(f"[PEER] [Auto] Στέλνω προσφορά: {new_bid} για {object_id}")
        result = send_request(conn, {
            "action":    "place_bid",
            "token_id":  token_id,
            "object_id": object_id,
            "bid":       new_bid,
        })
        if result:
            print(f"[PEER] [Auto] PlaceBid → {result.get('message')}")
        print("Επιλογή: ", end="", flush=True)


# ─────────────────────────────────────────────
#  ΠΑΡΑΓΩΓΗ ΑΝΤΙΚΕΙΜΕΝΩΝ & REQUEST AUCTION
# ─────────────────────────────────────────────

def generate_objects(peer_id: str) -> list:
    """Παράγει ένα αντικείμενο και το αποθηκεύει στο shared_directory."""
    obj_id    = f"Object_{peer_id}_{int(time.time())}"
    start_bid = round(random.uniform(10, 500), 2)
    duration  = random.choice([20, 30, 45, 60])

    obj = {
        "object_id":        obj_id,
        "description":      f"Αντικείμενο {obj_id} από peer {peer_id}",
        "start_bid":        start_bid,
        "auction_duration": duration,
    }

    filepath = os.path.join(SHARED_DIR, f"{obj_id}.txt")
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)

    print(f"[PEER] Παράχθηκε αντικείμενο: {obj_id} | "
          f"Τιμή εκκίνησης: {start_bid} | Διάρκεια: {duration}s")
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
            continue

        objects = generate_objects(peer_id)
        request_auction(conn, objects)


def request_auction(conn: socket.socket, objects: list):
    """Στέλνει λίστα αντικειμένων στον server για δημοπράτηση."""
    if token_id is None:
        print("[PEER] Πρέπει να είσαι logged in για request_auction.")
        return

    resp = send_request(conn, {
        "action":   "request_auction",
        "token_id": token_id,
        "objects":  objects,
    })
    if resp:
        print(f"[PEER] RequestAuction → {resp.get('message')}")


# ─────────────────────────────────────────────
#  TRANSACTION — peer-to-peer αγορά
# ─────────────────────────────────────────────

def do_transaction(win_msg: dict):
    """
    Εκτελείται σε background thread όταν ο peer κερδίσει δημοπρασία.
    Συνδέεται απευθείας στον πωλητή (peer-to-peer), επιβεβαιώνει
    την αγορά και παραλαμβάνει το αρχείο metadata.
    """
    object_id   = win_msg.get("object_id")
    winning_bid = win_msg.get("winning_bid")
    seller_ip   = win_msg.get("seller_ip")
    seller_port = win_msg.get("seller_port")

    if not seller_ip or not seller_port:
        print("[PEER] Transaction: Δεν υπάρχουν στοιχεία πωλητή.")
        return

    print(f"[PEER] Transaction: Συνδέομαι στον πωλητή {seller_ip}:{seller_port}...")

    try:
        conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        conn.settimeout(10)
        conn.connect((seller_ip, int(seller_port)))

        # Αυτή η σύνδεση είναι peer-to-peer — χρησιμοποιούμε send_msg/recv_msg απευθείας
        send_msg(conn, {
            "action":      "transaction_buy",
            "object_id":   object_id,
            "winning_bid": winning_bid,
            "buyer":       peer_username,
        })

        resp = recv_msg(conn)
        conn.close()

        if resp and resp.get("status") == "ok":
            metadata = resp.get("metadata")
            filepath = os.path.join(SHARED_DIR, f"{object_id}.txt")
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(metadata)
            print(f"[PEER] Transaction επιτυχής! Αρχείο αποθηκεύτηκε: {filepath}")
            notify_server_bought(object_id)
        else:
            print(f"[PEER] Transaction απέτυχε: "
                  f"{resp.get('message') if resp else 'Χωρίς απόκριση'}")

    except Exception as e:
        print(f"[PEER] Transaction error: {e}")


def notify_server_bought(object_id: str):
    """
    Ενημερώνει τον server ότι ο αγοραστής έχει παραλάβει το αντικείμενο.
    Χρησιμοποιεί send_msg (όχι send_request) γιατί ο server δεν στέλνει απάντηση.
    """
    send_msg(server_conn, {
        "action":    "confirm_purchase",
        "token_id":  token_id,
        "object_id": object_id,
    })


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
            threading.Thread(target=handle_incoming, args=(conn, addr), daemon=True).start()
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

    conn.close()


def handle_sell(conn, msg):
    """Στέλνει το αρχείο metadata στον αγοραστή και το διαγράφει τοπικά."""
    object_id = msg.get("object_id")
    filepath  = os.path.join(SHARED_DIR, f"{object_id}.txt")

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

    # Ο server_listener είναι ο ΜΟΝΟΣ που διαβάζει από το server_conn
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
