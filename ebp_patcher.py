import struct
import os
import shutil
import tkinter as tk
import time


#import ebp_patcher # Import the file above

## Example: Adding 5 clones of Worker 2 to a specific file
#ebp_patcher.patch_ebp("C:/Path/To/File.ebp", n_clones=5, q_source_id=2)




# --- CONSTANTS ---
WORKER_DATA_SIZE = 52 
# -----------------

def get_path_from_clipboard():
    """
    Retrieves text from the clipboard and sanitizes it 
    (removes surrounding quotes common in Windows "Copy as Path").
    """
    try:
        root = tk.Tk()
        root.withdraw()  # Hide the main window
        clip_text = root.clipboard_get()
        root.destroy()
        
        # Clean up the path (remove quotes and whitespace)
        clean_path = clip_text.strip().strip('"').strip("'")
        return clean_path
    except Exception as e:
        print(f"Error reading clipboard: {e}")
        return None

def patch_ebp(file_path, n_clones=1, q_source_id=1):
    """
    The core modular function.
    
    :param file_path: Absolute path to the .ebp file
    :param n_clones: Number of clones to add (N)
    :param q_source_id: The ID of the worker to duplicate data from (Q)
    :return: Boolean (True if successful, False if failed)
    """
    
    print(f"\n--- [MODULAR PATCHER] Processing: {os.path.basename(file_path)} ---")
    print(f"    Target: N={n_clones} (Clones), Q={q_source_id} (Source ID)")

    if not os.path.exists(file_path):
        print(f"ERROR: File not found: {file_path}")
        return False

    # 1. Backup
    backup_path = file_path + ".bak"
    try:
        shutil.copy(file_path, backup_path)
    except IOError as e:
        print(f"Error creating backup: {e}")
        return False

    try:
        with open(file_path, 'r+b') as f:
            # ===========================================================
            # PHASE 1: MAPPING AND GAP CALCULATION (PHYSICAL SORT)
            # ===========================================================
            
            f.seek(0, 2)
            original_file_size = f.tell()
            current_eof = original_file_size
            
            # Read Headers
            f.seek(0x74)
            old_total_workers = struct.unpack('<H', f.read(2))[0]
            old_nonsub_workers = struct.unpack('<H', f.read(2))[0] 

            if q_source_id >= old_total_workers:
                print(f"ERROR: Source Q ({q_source_id}) out of bounds.")
                return False

            # Define the "Growing Edge" (End of Pointer Table)
            ptr_table_end = 0x78 + (old_total_workers * 4)

            # Map all workers
            worker_locations = []
            f.seek(0x78)
            for i in range(old_total_workers):
                raw_ptr = f.read(4)
                ptr_val = struct.unpack('<I', raw_ptr)[0]
                data_loc = ptr_val + 0x40
                
                worker_locations.append({
                    'id': i,
                    'ptr_offset': 0x78 + (i * 4),
                    'data_loc': data_loc
                })

            # Sort by physical location to find blocking data
            worker_locations.sort(key=lambda x: x['data_loc'])

            # Gap Check Loop
            bytes_needed = n_clones * 4
            
            while True:
                # Get the worker physically closest to the pointer table
                if not worker_locations:
                    break # Should not happen unless file is empty of workers

                next_physical_worker = worker_locations[0]
                
                # Calculate Gap
                available_gap = next_physical_worker['data_loc'] - ptr_table_end
                if available_gap < 0: available_gap = 0 

                if available_gap >= bytes_needed:
                    # Space is sufficient
                    break
                
                # Move the obstacle to EOF
                victim = worker_locations.pop(0) 
                
                # Move Data
                f.seek(victim['data_loc'])
                victim_data = f.read(WORKER_DATA_SIZE)
                f.seek(current_eof)
                f.write(victim_data)
                
                # Update Pointer
                new_ptr_val = current_eof - 0x40
                f.seek(victim['ptr_offset'])
                f.write(struct.pack('<I', new_ptr_val))
                
                current_eof += WORKER_DATA_SIZE

            # ===========================================================
            # PHASE 2: APPEND TEMPLATE (From Source Q)
            # ===========================================================
            
            # Read fresh pointer for Q (in case it moved)
            f.seek(0x78 + (q_source_id * 4))
            template_ptr_val = struct.unpack('<I', f.read(4))[0]
            
            f.seek(template_ptr_val + 0x40)
            template_data = f.read(WORKER_DATA_SIZE)
            
            # Append template data to EOF
            clone_data_loc = current_eof
            f.seek(clone_data_loc)
            f.write(template_data)
            current_eof += WORKER_DATA_SIZE
            
            new_clones_ptr_target = clone_data_loc - 0x40

            # ===========================================================
            # PHASE 3: INJECT POINTERS
            # ===========================================================
            
            offset_insertion = 0x78 + (old_nonsub_workers * 4)
            offset_old_table_end = 0x78 + (old_total_workers * 4)
            
            # Shift Sub-Routines down
            size_to_shift = offset_old_table_end - offset_insertion
            if size_to_shift > 0:
                f.seek(offset_insertion)
                sub_routine_ptrs = f.read(size_to_shift)
                f.seek(offset_insertion + (n_clones * 4))
                f.write(sub_routine_ptrs)

            # Write New Pointers
            f.seek(offset_insertion)
            packed_ptr = struct.pack('<I', new_clones_ptr_target)
            for _ in range(n_clones):
                f.write(packed_ptr)

            # ===========================================================
            # PHASE 4: UPDATE HEADERS
            # ===========================================================
            
            f.seek(0x74)
            f.write(struct.pack('<H', old_total_workers + n_clones))
            f.seek(0x76)
            f.write(struct.pack('<H', old_nonsub_workers + n_clones))
            
            # Zeroing
            f.seek(0x52)
            f.write(b'\x00\x00\x00\x00')
            f.seek(0x56)
            f.write(b'\x00\x00')
            f.seek(0x5A)
            f.write(b'\x00\x00\x00\x00')

        # ===========================================================
        # PHASE 5: ID REPLACEMENT
        # ===========================================================
        
        with open(file_path, 'rb') as f:
            content = bytearray(f.read())
            
        start_id = old_total_workers
        end_id = old_nonsub_workers - 1
        
        for i in range(start_id, end_id, -1):
            pattern_old = b'\xB3' + struct.pack('<H', i)
            pattern_new = b'\xB3' + struct.pack('<H', i + n_clones)
            
            if pattern_old in content:
                content = content.replace(pattern_old, pattern_new)
                
        with open(file_path, 'wb') as f:
            f.write(content)

        print("--- Success. File updated. ---")
        return True

    except Exception as e:
        print(f"CRITICAL ERROR: {e}")
        return False

# ==================================================
# EXECUTION BLOCK (Runs only if file is run directly)
# ==================================================
if __name__ == "__main__":
    print("Reading file path from clipboard...")
    target_path = get_path_from_clipboard()
    
    if target_path:
        # Defaults: N=1, Q=1
        patch_ebp(target_path, n_clones=1, q_source_id=1)
    else:
        print("Clipboard was empty or invalid.")
        input("Press Enter to exit...")
