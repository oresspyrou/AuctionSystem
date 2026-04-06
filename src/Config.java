public class Config {
    public static final String SERVER_HOST = "127.0.0.1";
    public static final int SERVER_PORT = 9000;

    // items get generated every RAND * MAX_ITEM_INTERVAL seconds
    public static final int MAX_ITEM_INTERVAL = 120;

    // how often peers poll for the current auction (seconds)
    public static final int POLL_INTERVAL = 60;

    // 60% chance a peer is interested in bidding
    public static final double INTEREST_PROBABILITY = 0.6;

    // timeout for check_active ping (ms)
    public static final int CHECK_ACTIVE_TIMEOUT = 5000;
}
