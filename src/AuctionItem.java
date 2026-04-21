import java.io.BufferedReader;
import java.io.FileReader;
import java.io.FileWriter;
import java.io.IOException;

// represents an item up for auction
// matches the file format from the assignment:
// object_id: Object_01; description: Vintage watch; start_bid: 50.0; auction_duration: 120
public class AuctionItem {
    public String objectId;
    public String description;
    public double startBid;
    public int duration; // in seconds
    public String sellerTokenId;

    public AuctionItem(String objectId, String description, double startBid, int duration) {
        this.objectId = objectId;
        this.description = description;
        this.startBid = startBid;
        this.duration = duration;
        this.sellerTokenId = null;
    }

    // format used inside pipe-separated protocol messages
    // fields separated by semicolons: Object_01;Vintage watch;50.0;120
    public String toProtocolString() {
        return objectId + ";" + description + ";" + startBid + ";" + duration;
    }

    // parse from the semicolon format used in protocol messages
    public static AuctionItem fromProtocolString(String s) {
        String[] parts = s.split(";");
        // if the message doesn't have all 4 parts, it's invalid
        if (parts.length < 4) return null;
        
        // data cleaning - trim whitespace and parse numbers
        String id = parts[0].trim();
        String desc = parts[1].trim();
        double bid = Double.parseDouble(parts[2].trim());
        int dur = Integer.parseInt(parts[3].trim());

        return new AuctionItem(id, desc, bid, dur);
    }

    // save to file in the assignment's format
    public void saveToFile(String path) throws IOException {
        FileWriter fw = new FileWriter(path);
        fw.write("object_id: " + objectId + "; description: " + description
                + "; start_bid: " + startBid + "; auction_duration: " + duration);
        fw.close();
    }

    // create an AuctionItem from a file containing a single line in the assignment's format
    public static AuctionItem parseFromFile(String path) throws IOException {
        BufferedReader br = new BufferedReader(new FileReader(path));
        String line = br.readLine();
        br.close();

        if (line == null || line.isEmpty()) return null;
        return parseFromFileFormat(line);
    }

    // parse the "object_id: X; description: Y; start_bid: Z; auction_duration: W" format
    // helps in robustness, security and following the formats specified in the assignment
    private static AuctionItem parseFromFileFormat(String line) {
        // split by "; " to get each key-value pair
        String[] parts = line.split("; ");

        String id = null;
        String desc = null;
        double bid = 0;
        int dur = 0;

        for (String part : parts) {
            String[] kv = part.split(": ", 2);
            if (kv.length < 2) continue;

            String key = kv[0].trim();
            String value = kv[1].trim();

            if (key.equals("object_id")) {
                id = value;
            } else if (key.equals("description")) {
                desc = value;
            } else if (key.equals("start_bid")) {
                bid = Double.parseDouble(value);
            } else if (key.equals("auction_duration")) {
                dur = Integer.parseInt(value);
            }
        }

        if (id == null) return null;
        return new AuctionItem(id, desc, bid, dur);
    }

    @Override
    public String toString() {
        return "AuctionItem{" + objectId + ", " + description + ", startBid=" + startBid + ", duration=" + duration + "s}";
    }
}
