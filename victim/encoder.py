#!/usr/bin/env python3
import argparse, math, os
from PIL import Image

# Configuration constants.
DEFAULT_BORDER = 20         # Outer border thickness (in pixels)
HEADER_HEIGHT = 50          # Height of header band (drawn in the data region)
MARKER_COLOR = 128          # Marker color (should not be a multiple of 17)
MIN_CELL = 1                # Minimum cell size (in pixels) for robustness

# File name header: Use 2 bytes for file name length and 256 bytes for file name.
FILENAME_FIELD_SIZE = 256
FILENAME_LENGTH_FIELD_SIZE = 2  # Using 2 bytes for filename length
HEADER_EXTRA = FILENAME_LENGTH_FIELD_SIZE + FILENAME_FIELD_SIZE

# New header structure:
#   • 4 bytes: payload length (in bytes) for this fragment
#   • 2 bytes: grid_cols (payload grid columns)
#   • 2 bytes: grid_rows (payload grid rows)
#   • 4 bytes: fragment index (starting at 1)
#   • 4 bytes: total fragments
#   • 1 byte: dummy border thickness (B)
#   • 2 bytes: expected overall image width
#   • 2 bytes: expected overall image height
#   • 2 bytes: file name length (L)
#   • 256 bytes: file name (UTF‑8, padded/truncated)
HEADER_FIXED_BYTES = 4 + 2 + 2 + 4 + 4 + 1 + 2 + 2  # =21 bytes
HEADER_BYTES = HEADER_FIXED_BYTES + HEADER_EXTRA         # = 21 + 258 = 279 bytes
HEADER_NIBBLES = HEADER_BYTES * 2

def nibble_to_gray(nibble):
    """Map a nibble (0–15) to an 8‑bit grayscale value."""
    return nibble * 17

def draw_nested_frames(img, width, height, border, num_frames=2):
    """
    Draw nested (photo-frame style) borders in the outer border area.
    Each frame is drawn with a constant grayscale color.
    """
    frame_thickness = border // num_frames
    for i in range(num_frames):
        left = i * frame_thickness
        top = i * frame_thickness
        right = width - i * frame_thickness - 1
        bottom = height - i * frame_thickness - 1
        color = nibble_to_gray(i)
        # Top border.
        for y in range(top, top + frame_thickness):
            for x in range(left, right + 1):
                img.putpixel((x, y), color)
        # Bottom border.
        for y in range(bottom - frame_thickness + 1, bottom + 1):
            for x in range(left, right + 1):
                img.putpixel((x, y), color)
        # Left border.
        for x in range(left, left + frame_thickness):
            for y in range(top, bottom + 1):
                img.putpixel((x, y), color)
        # Right border.
        for x in range(right - frame_thickness + 1, right + 1):
            for y in range(top, bottom + 1):
                img.putpixel((x, y), color)

def draw_marker_lines(img, safe_x, safe_y, safe_width, safe_height, marker_color=MARKER_COLOR):
    """
    Draw 1-pixel–thick marker lines along the boundary of the safe region.
    These markers allow the decoder to determine the actual data region.
    """
    for x in range(safe_x, safe_x + safe_width):
        img.putpixel((x, safe_y), marker_color)                  # top
        img.putpixel((x, safe_y + safe_height - 1), marker_color)  # bottom
    for y in range(safe_y, safe_y + safe_height):
        img.putpixel((safe_x, y), marker_color)                  # left
        img.putpixel((safe_x + safe_width - 1, y), marker_color)   # right

def encode_fragment(fragment_data, output_file, image_width, image_height, border, frag_index, total_fragments, file_name):
    # Overall safe region is the overall image minus the outer border.
    safe_width = image_width - 2 * border
    safe_height = image_height - 2 * border
    if safe_width <= 2 or safe_height <= (HEADER_HEIGHT + 2):
        raise ValueError("Image dimensions too small for chosen border and header height.")
    
    # The data region is the safe region with a 1-pixel marker rim removed.
    data_x = border + 1
    data_y = border + 1
    data_width = safe_width - 2
    data_height = safe_height - 2
    
    # Determine grid dimensions based on the minimum cell size.
    grid_cols = data_width // MIN_CELL
    grid_rows = (data_height - HEADER_HEIGHT) // MIN_CELL
    total_cells = grid_cols * grid_rows
    max_payload = total_cells // 2  # 2 nibbles per byte
    
    if len(fragment_data) > max_payload:
        raise ValueError("Fragment data exceeds maximum payload for one image at the chosen minimum cell size.")
    
    # Build header fixed part.
    header_bytes = (
        len(fragment_data).to_bytes(4, 'big') +
        grid_cols.to_bytes(2, 'big') +
        grid_rows.to_bytes(2, 'big') +
        frag_index.to_bytes(4, 'big') +
        total_fragments.to_bytes(4, 'big') +
        border.to_bytes(1, 'big') +
        image_width.to_bytes(2, 'big') +
        image_height.to_bytes(2, 'big')
    )
    
    # Build file name field: 2 bytes for length + 256 bytes for file name.
    file_name_bytes = os.path.basename(file_name).encode('utf-8')
    if len(file_name_bytes) > FILENAME_FIELD_SIZE:
        file_name_bytes = file_name_bytes[:FILENAME_FIELD_SIZE]
    file_name_field = len(file_name_bytes).to_bytes(2, 'big') + file_name_bytes.ljust(FILENAME_FIELD_SIZE, b'\0')
    
    header_bytes += file_name_field
    
    if len(header_bytes) != HEADER_BYTES:
        raise ValueError("Header byte count error.")
    
    # Convert header to nibble stream.
    header_nibbles = []
    for b in header_bytes:
        header_nibbles.append(b >> 4)
        header_nibbles.append(b & 0x0F)
    
    # Convert payload to nibble stream.
    payload_nibbles_list = []
    for byte in fragment_data:
        payload_nibbles_list.append(byte >> 4)
        payload_nibbles_list.append(byte & 0x0F)
    if len(payload_nibbles_list) < total_cells:
        payload_nibbles_list.extend([0] * (total_cells - len(payload_nibbles_list)))
    
    # Create overall image.
    img = Image.new("L", (image_width, image_height), color=0)
    draw_nested_frames(img, image_width, image_height, border, num_frames=2)
    safe_x = border
    safe_y = border
    draw_marker_lines(img, safe_x, safe_y, safe_width, safe_height, marker_color=MARKER_COLOR)
    
    # Draw header into the data region.
    header_cell_width = data_width / HEADER_NIBBLES
    for i, nib in enumerate(header_nibbles):
        cell_left = data_x + round(i * data_width / HEADER_NIBBLES)
        cell_right = data_x + round((i + 1) * data_width / HEADER_NIBBLES)
        for y in range(data_y, data_y + HEADER_HEIGHT):
            for x in range(cell_left, cell_right):
                img.putpixel((x, y), nibble_to_gray(nib))
    
    # Draw payload grid in the data region below the header.
    payload_area_top = data_y + HEADER_HEIGHT
    for idx, nib in enumerate(payload_nibbles_list):
        r = idx // grid_cols
        c = idx % grid_cols
        cell_left = data_x + round(c * data_width / grid_cols)
        cell_right = data_x + round((c + 1) * data_width / grid_cols)
        cell_top = payload_area_top + round(r * (data_height - HEADER_HEIGHT) / grid_rows)
        cell_bottom = payload_area_top + round((r + 1) * (data_height - HEADER_HEIGHT) / grid_rows)
        for y in range(cell_top, cell_bottom):
            for x in range(cell_left, cell_right):
                img.putpixel((x, y), nibble_to_gray(nib))
    
    img.save(output_file, format="PNG")
    print(f"Encoded fragment {frag_index}/{total_fragments} to {output_file}.")
    print(f"Overall image: {image_width}×{image_height} with {border}px border.")
    print(f"Data region: {data_width}×{data_height} (Header: {HEADER_HEIGHT}px, Grid: {grid_cols}×{grid_rows}).")
    print(f"Fragment payload: {len(fragment_data)} bytes.")

def main():
    parser = argparse.ArgumentParser(
        description="Optimized encoder with fragmentation support, extended file name (256 bytes), and 4-byte fragment count."
    )
    parser.add_argument("input_file", help="Input file to encode (binary or hex string)")
    parser.add_argument("output_file", help="Base output PNG filename (fragment index will be appended if needed)")
    parser.add_argument("--image_width", type=int, default=1920, help="Overall image width (default: 1920)")
    parser.add_argument("--image_height", type=int, default=1080, help="Overall image height (default: 1080)")
    parser.add_argument("--border", type=int, default=DEFAULT_BORDER, help="Outer border thickness (default: 20)")
    parser.add_argument("--req_id", type=str, help="Request ID")
    parser.add_argument("--hex", action="store_true", help="Treat input file as a hex string")
    args = parser.parse_args()
    
    if args.hex:
        with open(args.input_file, 'r') as f:
            data = bytes.fromhex(f.read().strip())
    else:
        with open(args.input_file, 'rb') as f:
            data = f.read()
    
    # Compute maximum payload per image.
    safe_width = args.image_width - 2 * args.border
    safe_height = args.image_height - 2 * args.border
    data_width = safe_width - 2   # data region width (after marker rim)
    data_height = safe_height - 2  # data region height (after marker rim)
    payload_area_height = data_height - HEADER_HEIGHT
    grid_cols_max = data_width // MIN_CELL
    grid_rows_max = payload_area_height // MIN_CELL
    total_cells = grid_cols_max * grid_rows_max
    max_payload = total_cells // 2  # 2 nibbles per byte
    print(f"Maximum payload per image: {max_payload} bytes (Data region: {data_width}×{payload_area_height}).")
    
    total_data_len = len(data)
    total_fragments = math.ceil(total_data_len / max_payload)
    print(f"Total input data: {total_data_len} bytes, requiring {total_fragments} fragment(s).")
    
    # Use original file name from input path.
    orig_file_name = os.path.basename(args.input_file)
    
    for frag_index in range(1, total_fragments + 1):
        start = (frag_index - 1) * max_payload
        end = start + max_payload
        fragment_data = data[start:end]
        if total_fragments > 1:
            base, ext = os.path.splitext(args.output_file)
            out_file = f"{base}_{frag_index:03d}{ext}"
        else:
            out_file = args.output_file
        encode_fragment(fragment_data, out_file, args.image_width, args.image_height, args.border,
                        frag_index, total_fragments, orig_file_name)

if __name__ == "__main__":
    main()
