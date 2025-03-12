#!/usr/bin/env python3
import argparse, math, os, glob
from PIL import Image

# These constants must match those used by the encoder.
HEADER_HEIGHT = 50           # Height of header band in the data region
FILENAME_FIELD_SIZE = 256    # Must match encoder’s value.
FILENAME_LENGTH_FIELD_SIZE = 2
HEADER_EXTRA = FILENAME_LENGTH_FIELD_SIZE + FILENAME_FIELD_SIZE
HEADER_FIXED_BYTES = 4 + 2 + 2 + 4 + 4 + 1 + 2 + 2  # =21 bytes
HEADER_BYTES = HEADER_FIXED_BYTES + HEADER_EXTRA         # = 21 + 258 = 279 bytes
HEADER_NIBBLES = HEADER_BYTES * 2
MARKER_COLOR = 128           # Marker color (should not be a multiple of 17)

def color_to_nibble(gray_val):
    """Convert an 8-bit grayscale value to a nibble (0–15)."""
    return gray_val // 17

def find_marker_edges(img, threshold=0.8, search_window=100, debug=False):
    """
    Scan near each edge of the image (within 'search_window' pixels) to detect marker lines.
    A row/column is accepted if at least 'threshold' fraction of its pixels equal MARKER_COLOR.
    Returns (top, bottom, left, right) coordinates.
    """
    width, height = img.size

    def check_row(y):
        count = sum(1 for x in range(width) if img.getpixel((x, y)) == MARKER_COLOR)
        fraction = count / width
        if debug:
            print(f"Row {y}: {fraction*100:.1f}% marker")
        return fraction

    def check_col(x):
        count = sum(1 for y in range(height) if img.getpixel((x, y)) == MARKER_COLOR)
        fraction = count / height
        if debug:
            print(f"Col {x}: {fraction*100:.1f}% marker")
        return fraction

    top = next((y for y in range(0, min(search_window, height)) if check_row(y) >= threshold), None)
    bottom = next((y for y in range(height - 1, max(height - search_window, 0) - 1, -1) if check_row(y) >= threshold), None)
    left = next((x for x in range(0, min(search_window, width)) if check_col(x) >= threshold), None)
    right = next((x for x in range(width - 1, max(width - search_window, 0) - 1, -1) if check_col(x) >= threshold), None)

    if None in (top, bottom, left, right):
        raise ValueError("Failed to detect marker lines on one or more sides.")
    return top, bottom, left, right

def extract_header(img, data_x, data_y, data_width):
    """Extract the header from the top of the data region."""
    header_nibbles = []
    for i in range(HEADER_NIBBLES):
        cell_left = data_x + round(i * data_width / HEADER_NIBBLES)
        cell_right = data_x + round((i + 1) * data_width / HEADER_NIBBLES)
        center_x = (cell_left + cell_right) // 2
        center_y = data_y + HEADER_HEIGHT // 2
        header_nibbles.append(color_to_nibble(img.getpixel((center_x, center_y))))
    header_bytes = bytearray()
    for i in range(0, HEADER_NIBBLES, 2):
        header_bytes.append((header_nibbles[i] << 4) | header_nibbles[i+1])
    return header_bytes

def decode_fragment(filename, threshold, search_window, debug, fb_width, fb_height, fb_border):
    """
    Decodes a fragment image:
      - Uses marker detection (or fallback if needed) to define the data region.
      - Extracts the header and payload grid.
    Returns a tuple: (fragment index, total fragments, payload bytes, file_name, header_signature)
    where header_signature is (expected_width_from_header, expected_height_from_header, border_in_header, file_name).
    """
    img = Image.open(filename).convert("L")
    rec_width, rec_height = img.size
    print(f"Processing {filename} (size: {rec_width}×{rec_height})")
    
    fallback_used = False
    try:
        top_marker, bottom_marker, left_marker, right_marker = find_marker_edges(img, threshold, search_window, debug)
        print(f"  Detected markers: top={top_marker}, bottom={bottom_marker}, left={left_marker}, right={right_marker}")
    except ValueError:
        fallback_used = True
        offset_x = (fb_width - rec_width) // 2
        top_marker = fb_border
        left_marker = fb_border - offset_x
        right_marker = fb_width - fb_border - 1 - offset_x
        bottom_marker = fb_height - fb_border - 1
        print("  Marker detection failed; using fallback based on expected dimensions:")
        print(f"    Fallback markers: top={top_marker}, bottom={bottom_marker}, left={left_marker}, right={right_marker}")
    
    safe_x = left_marker
    safe_y = top_marker
    safe_width = right_marker - left_marker + 1
    safe_height = bottom_marker - top_marker + 1
    data_x = safe_x + 1
    data_y = safe_y + 1
    data_width = safe_width - 2
    data_height = safe_height - 2
    
    header_bytes = extract_header(img, data_x, data_y, data_width)
    if len(header_bytes) != HEADER_BYTES:
        raise ValueError("Header extraction failed.")
    
    # Parse header fixed part.
    payload_length = int.from_bytes(header_bytes[0:4], 'big')
    grid_cols = int.from_bytes(header_bytes[4:6], 'big')
    grid_rows = int.from_bytes(header_bytes[6:8], 'big')
    header_frag_index = int.from_bytes(header_bytes[8:12], 'big')
    total_fragments = int.from_bytes(header_bytes[12:16], 'big')
    border_in_header = header_bytes[16]
    expected_width_from_header = int.from_bytes(header_bytes[17:19], 'big')
    expected_height_from_header = int.from_bytes(header_bytes[19:21], 'big')
    
    # Parse file name field.
    file_name_length = int.from_bytes(header_bytes[21:23], 'big')
    file_name_bytes = header_bytes[23:23+FILENAME_FIELD_SIZE]
    file_name = file_name_bytes[:file_name_length].decode('utf-8', errors='replace')
    
    if fallback_used:
        print("  Overriding header values with fallback parameters.")
        border_in_header = fb_border
        expected_width_from_header = fb_width
        expected_height_from_header = fb_height
    
    print("  Decoded header:")
    print(f"    Payload length: {payload_length} bytes")
    print(f"    Grid: {grid_cols} cols x {grid_rows} rows")
    print(f"    Fragment (header): {header_frag_index}/{total_fragments}")
    print(f"    Border (in header): {border_in_header}px")
    print(f"    Expected overall (header): {expected_width_from_header}×{expected_height_from_header}")
    print(f"    File name: {file_name}")
    print(f"    Data region (from markers/fallback): ({data_x}, {data_y}) {data_width}×{data_height}")
    
    # Skip fragments with zero payload.
    if payload_length == 0:
        raise ValueError("Invalid fragment: payload length is zero.")
    
    header_signature = (expected_width_from_header, expected_height_from_header, border_in_header, file_name)
    
    payload_area_top = data_y + HEADER_HEIGHT
    payload_area_height = data_height - HEADER_HEIGHT
    payload_nibbles = []
    for r in range(grid_rows):
        for c in range(grid_cols):
            cell_left = data_x + round(c * data_width / grid_cols)
            cell_right = data_x + round((c + 1) * data_width / grid_cols)
            cell_top = payload_area_top + round(r * payload_area_height / grid_rows)
            cell_bottom = payload_area_top + round((r + 1) * payload_area_height / grid_rows)
            center_x = (cell_left + cell_right) // 2
            center_y = (cell_top + cell_bottom) // 2
            payload_nibbles.append(color_to_nibble(img.getpixel((center_x, center_y))))
    expected_nibbles = payload_length * 2
    if len(payload_nibbles) < expected_nibbles:
        raise ValueError("Extracted payload is smaller than expected.")
    payload_bytes = bytearray()
    for i in range(0, expected_nibbles, 2):
        payload_bytes.append((payload_nibbles[i] << 4) | payload_nibbles[i+1])
    
    return header_frag_index, total_fragments, payload_bytes, file_name, header_signature

def main():
    parser = argparse.ArgumentParser(
        description="Decoder with fallback, extended file name extraction, and 4-byte fragment count."
    )
    parser.add_argument("input_png", nargs="+", help="Input PNG file(s) (fragments)")
    parser.add_argument("--threshold", type=float, default=0.8, help="Marker detection threshold (default: 0.8)")
    parser.add_argument("--search_window", type=int, default=100, help="Search window in pixels (default: 100)")
    parser.add_argument("--debug", action="store_true", help="Enable debug output for marker detection")
    parser.add_argument("--fallback_width", type=int, default=1920, help="Fallback overall image width (default: 1920)")
    parser.add_argument("--fallback_height", type=int, default=1080, help="Fallback overall image height (default: 1080)")
    parser.add_argument("--fallback_border", type=int, default=20, help="Fallback outer border thickness (default: 20)")
    parser.add_argument("--total_fragments_override", type=int, help="Override total fragments count from header")
    parser.add_argument("--use_filename_order", action="store_true", help="Ignore header fragment numbers and assign based on sorted filenames")
    args = parser.parse_args()

    filenames = sorted(args.input_png)
    fragments = {}
    file_name_extracted = None
    common_header = None  # To store the signature from the first valid fragment.
    
    for i, filename in enumerate(filenames, start=1):
        try:
            frag_index, frag_total, frag_data, frag_file_name, header_sig = decode_fragment(
                filename,
                args.threshold,
                args.search_window,
                args.debug,
                args.fallback_width,
                args.fallback_height,
                args.fallback_border
            )
            # Only set common_header if not already set.
            if common_header is None:
                common_header = header_sig
            else:
                # Skip fragments whose header signature does not match the common header.
                if header_sig != common_header:
                    print(f"Skipping {filename}: header signature {header_sig} does not match common header {common_header}.")
                    continue

            if args.use_filename_order:
                assigned_index = i
                print(f"File {os.path.basename(filename)} assigned as fragment {assigned_index} (header said {frag_index}).")
                frag_index = assigned_index
                frag_total = len(filenames)
            else:
                print(f"File {os.path.basename(filename)} decoded as fragment {frag_index}.")
        except Exception as e:
            print(f"Error decoding {filename}: {e}")
            continue
        
        if args.total_fragments_override:
            frag_total = args.total_fragments_override
        if frag_index in fragments:
            print(f"Warning: Duplicate fragment index {frag_index} found in {filename}; skipping duplicate.")
        else:
            fragments[frag_index] = frag_data
            if file_name_extracted is None:
                file_name_extracted = frag_file_name

    # Ensure we have all fragments based on the collected keys.
    if not fragments:
        raise ValueError("No valid fragments found.")
    sorted_keys = sorted(fragments.keys())
    full_data = bytearray()
    for key in sorted_keys:
        full_data.extend(fragments[key])
    
    if file_name_extracted is None or file_name_extracted == "":
        raise ValueError("No valid file name found in fragment headers.")
    output_file = file_name_extracted
    with open(output_file, "wb") as f:
        f.write(full_data)
    print(f"Reconstructed data saved to {output_file}")
    
    # Cleanup: delete blank.png and any file ending with -0001.png
    for f in glob.glob("blank.png"):
        try:
            os.remove(f)
            print(f"Deleted {f}")
        except Exception as e:
            print(f"Error deleting {f}: {e}")
    for f in glob.glob("*-0001.png"):
        try:
            os.remove(f)
            print(f"Deleted {f}")
        except Exception as e:
            print(f"Error deleting {f}: {e}")

if __name__ == "__main__":
    main()
