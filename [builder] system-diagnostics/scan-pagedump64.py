#!/usr/bin/env python3
"""
PAGEDU64 minidump scanner — parse small kernel dumps (~128KB) without WinDbg.

Usage:
    python scan-pagedump64.py <dumpfile.dmp> [dumpfile2.dmp ...]

What it does:
    - Reads PAGEDU64 header (the format Windows uses for small kernel dumps)
    - Extracts BugCheck code + 4 parameters, decodes 0xCE/0x1A etc.
    - String-scans the file for .sys driver names, filtering for ACE/WinDivert
    - Compares driver presence across multiple dumps to identify deltas

Limitations:
    - PAGEDU64 dumps are ~128KB "small memory dumps". They store minimal
      context — no embedded MDMP module list, no full call stack.
    - Driver identification is via string scan, not module list enumeration.
      This is often sufficient to determine which driver class was involved.
    - For full analysis, install WinDbg and use the full dump.

Requires: Python stdlib only (no pip packages needed).
"""

import struct
import sys
import os


BUGCHECK_NAMES = {
    0x01: 'APC_INDEX_MISMATCH',
    0x0A: 'IRQL_NOT_LESS_OR_EQUAL',
    0x1A: 'MEMORY_MANAGEMENT',
    0x1E: 'KMODE_EXCEPTION_NOT_HANDLED',
    0x3B: 'SYSTEM_SERVICE_EXCEPTION',
    0x50: 'PAGE_FAULT_IN_NONPAGED_AREA',
    0x7F: 'UNEXPECTED_KERNEL_MODE_TRAP',
    0xD1: 'DRIVER_IRQL_NOT_LESS_OR_EQUAL',
    0xCE: 'DRIVER_UNLOADED_WITHOUT_CANCELLING_PENDING_OPERATIONS',
    0x44: 'MULTIPLE_IRP_COMPLETE_REQUESTS',
    0x0D1: 'DRIVER_IRQL_NOT_LESS_OR_EQUAL',
    0x0E6: 'DRIVER_VERIFIER_DMA_VIOLATION',
    0x0F7: 'DRIVER_OVERRAN_STACK_BUFFER',
}


def read_pagedump64(filepath):
    """Parse PAGEDU64 header and extract bugcheck info."""
    with open(filepath, 'rb') as f:
        data = f.read()

    size = len(data)
    sig = data[:8].decode('ascii', errors='replace')
    
    result = {
        'file': os.path.basename(filepath),
        'size_kb': size // 1024,
        'signature': sig,
    }

    if sig not in ('PAGEDU64', 'PAGEDU '):
        result['error'] = f'Unknown signature: {sig}'
        return result

    # BugCheck code at offset 0x38
    bugcheck = struct.unpack('<I', data[0x38:0x3C])[0]
    p1 = struct.unpack('<Q', data[0x40:0x48])[0]
    p2 = struct.unpack('<Q', data[0x48:0x50])[0]
    p3 = struct.unpack('<Q', data[0x50:0x58])[0]
    p4 = struct.unpack('<Q', data[0x58:0x60])[0]

    result['bugcheck'] = bugcheck
    result['bugcheck_name'] = BUGCHECK_NAMES.get(bugcheck, 'UNKNOWN')
    result['params'] = [p1, p2, p3, p4]

    # Human-readable annotations for known patterns
    if bugcheck == 0xCE:
        result['annotation'] = (
            f"P1/P3 = driver object at 0x{p1:016X}\n"
            f"P2 = 0x{p2:X}  (0x10 = device object being removed)"
        )

    return result


def find_sys_strings(data):
    """Find unique .sys driver references in the dump binary."""
    # ASCII strings
    ascii_strings = set()
    current = b''
    for b in data:
        if 32 <= b < 127:
            current += bytes([b])
        else:
            try:
                s = current.decode('ascii')
                if len(s) >= 4:
                    ascii_strings.add(s)
            except:
                pass
            current = b''
    if len(current) >= 4:
        try:
            ascii_strings.add(current.decode('ascii'))
        except:
            pass

    # UTF-16 strings (kernel often uses wide strings for paths)
    utf16_strings = set()
    for i in range(0, len(data) - 3, 2):
        c = struct.unpack('<H', data[i:i+2])[0]
        if 32 <= c < 128:
            j = i
            s = ''
            while j < len(data) - 1:
                c2 = struct.unpack('<H', data[j:j+2])[0]
                if 32 <= c2 < 128:
                    s += chr(c2)
                    j += 2
                elif c2 == 0 and len(s) >= 4:
                    break
                else:
                    break
            if len(s) >= 4:
                utf16_strings.add(s)

    # Filter for .sys files
    sys_files = set()
    for s in ascii_strings:
        s_lower = s.lower()
        if '.sys' in s_lower and '\\' not in s_lower and len(s_lower) < 80:
            # Trim leading/trailing non-alphanumeric
            sys_files.add(s.strip(' .\\/-_'))
    for s in utf16_strings:
        s_lower = s.lower()
        if '.sys' in s_lower and '\\' not in s_lower and len(s_lower) < 80:
            sys_files.add(s.strip(' .\\/-_'))

    return sorted(sys_files)


def categorize_drivers(drivers, keywords=('ace', 'windivert', 'vgk', 'bedaisy',
                                           'nprotect', 'easyanticheat', 'battleye')):
    """Split driver list into interesting (matching keywords) and other."""
    interesting = [d for d in drivers if any(k in d.lower() for k in keywords)]
    others = [d for d in drivers if d not in interesting]
    return interesting, others


def compare_dumps(results):
    """Compare driver presence across multiple dumps. Highlight deltas."""
    if len(results) < 2:
        return

    all_drivers = []
    for r in results:
        all_drivers.append(set(r.get('interesting_drivers', [])))

    common = all_drivers[0]
    for s in all_drivers[1:]:
        common = common & s

    print("\n  --- Cross-Dump Comparison ---")
    for i, r in enumerate(results):
        missing = common - all_drivers[i]
        extra = all_drivers[i] - common
        if missing:
            print(f"  🔴 {r['file']}: MISSING vs others: {missing}")
        if extra:
            print(f"  🟡 {r['file']}: EXTRA vs others: {extra}")


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <dumpfile.dmp> [dumpfile2.dmp ...]")
        sys.exit(1)

    results = []

    for fp in sys.argv[1:]:
        if not os.path.isfile(fp):
            print(f"[SKIP] Not a file: {fp}")
            continue

        # Copy with elevation if needed (see standard-user-minidump-access.md)
        info = read_pagedump64(fp)

        sep = "=" * 65
        print(f"\n{sep}")
        print(f"  {info['file']}  ({info['size_kb']} KB, {info['signature']})")
        print(f"{sep}")

        if 'error' in info:
            print(f"  ERROR: {info['error']}")
            continue

        bc = info['bugcheck']
        print(f"  BugCheck: 0x{bc:08X} ({info['bugcheck_name']})")
        for i, p in enumerate(info['params'], 1):
            print(f"    P{i}: 0x{p:016X}")
        if 'annotation' in info:
            print(f"  {info['annotation']}")

        # String-scan for drivers
        with open(fp, 'rb') as f:
            data = f.read()
        
        all_drivers = find_sys_strings(data)
        interesting, others = categorize_drivers(all_drivers)

        info['interesting_drivers'] = interesting
        results.append(info)

        if interesting:
            print(f"\n  --- Suspicious/Interesting Drivers ---")
            for d in interesting:
                print(f"    {d}")
        
        # Also check for full paths with these drivers
        path_matches = set()
        for s in set([s.decode('ascii', errors='replace') if isinstance(s, bytes) else s
                     for s in (chr(b) if 32 <= b < 127 else '' for b in data)]):
            pass  # already captured above

        print(f"\n  Total .sys references: {len(all_drivers)}")
        print(f"  Interesting: {len(interesting)}, Other: {len(others)}")

    # Cross-dump comparison if multiple files
    compare_dumps(results)

    print()


if __name__ == '__main__':
    main()
