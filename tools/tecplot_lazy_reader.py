#!/usr/bin/env python3
import re
import sys
from typing import List, Dict, Generator

FLOAT_RE = re.compile(r"^[\s]*[+\-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+\-]?\d+)?")

class TecplotLazyReader:
    def __init__(self, path: str):
        self.path = path
        self.variables: List[str] = []
        self.zone: Dict[str,int] = {}
        self.datapacking = None
        self.varlocation = None
        self.data_start_pos = None

    def parse_header(self):
        with open(self.path, 'r', encoding='utf-8', errors='replace') as f:
            in_variables = False
            vars_buf = []
            in_zone_section = False
            while True:
                pos = f.tell()
                line = f.readline()
                if not line:
                    break
                l = line.strip()
                
                # Detect ZONE section start (ends variables section if active)
                if l.upper().startswith('ZONE'):
                    if in_variables:
                        in_variables = False
                        self.variables = vars_buf
                    in_zone_section = True
                
                # Detect VARIABLES block
                if l.upper().startswith('VARIABLES') and not in_zone_section:
                    in_variables = True
                    found = re.findall(r'"([^"]+)"', line)
                    vars_buf.extend(found)
                    continue
                if in_variables:
                    found = re.findall(r'"([^"]+)"', line)
                    if found:
                        vars_buf.extend(found)
                        continue
                    else:
                        in_variables = False
                        self.variables = vars_buf
                
                # Parse zone parameters (can span multiple lines)
                if in_zone_section:
                    # parse I=, J=, K=
                    for m in re.finditer(r'([IJK])\s*=\s*(\d+)', line, re.IGNORECASE):
                        self.zone[m.group(1).upper()] = int(m.group(2))
                    # datapacking
                    m = re.search(r'DATAPACKING\s*=\s*(\w+)', line, re.IGNORECASE)
                    if m:
                        self.datapacking = m.group(1)
                    # varlocation
                    if 'VARLOCATION' in l.upper():
                        self.varlocation = l
                
                # Detect first numeric line (end of header)
                if FLOAT_RE.match(line):
                    self.data_start_pos = pos
                    break
            
            if not self.variables and vars_buf:
                self.variables = vars_buf

    def _float_generator(self) -> Generator[float, None, None]:
        # yield floats sequentially from data_start_pos
        with open(self.path, 'r', encoding='utf-8', errors='replace') as f:
            if self.data_start_pos is None:
                self.parse_header()
            f.seek(self.data_start_pos)
            buf = ''
            while True:
                chunk = f.read(65536)
                if not chunk:
                    if buf:
                        for tok in buf.split():
                            yield float(tok)
                    break
                buf += chunk
                parts = buf.split()
                # keep last partial token in buf if chunk ended mid-token
                if chunk[-1].isspace():
                    buf = ''
                else:
                    # assume last part may be incomplete
                    buf = parts.pop() if parts else ''
                for tok in parts:
                    yield float(tok)

    def sample_variable(self, var_index:int, count:int=20) -> List[float]:
        # var_index is 1-based
        if self.data_start_pos is None:
            self.parse_header()
        if not self.zone:
            # try to parse again but still proceed
            pass
        I = self.zone.get('I', 1)
        J = self.zone.get('J', 1)
        K = self.zone.get('K', 1)
        N = I * J * K
        total_vars = len(self.variables) if self.variables else None
        if total_vars:
            if var_index < 1 or var_index > total_vars:
                raise ValueError('var_index out of range')
        gen = self._float_generator()
        to_skip = (var_index - 1) * N if N>0 else 0
        skipped = 0
        # skip tokens
        while skipped < to_skip:
            try:
                next(gen)
                skipped += 1
            except StopIteration:
                break
        # collect
        out = []
        collected = 0
        while collected < count:
            try:
                out.append(next(gen))
                collected += 1
            except StopIteration:
                break
        return out

    def extract_2d_slice(self, plane='XY', index:int=0, var_indices: List[int]=None, output_csv:str=None):
        """
        Extract a 2D slice from the 3D structured grid.
        
        plane: 'XY' (const Z), 'XZ' (const Y), or 'YZ' (const X)
        index: which plane index (0 to K-1 for XY, etc.)
        var_indices: list of 1-based variable indices to extract (default: [1,2,3] for X,Y,Z)
        output_csv: if provided, save slice to this CSV file
        
        Returns dict with grid and data.
        """
        if self.data_start_pos is None:
            self.parse_header()
        
        I = self.zone.get('I', 1)
        J = self.zone.get('J', 1)
        K = self.zone.get('K', 1)
        N = I * J * K
        
        if var_indices is None:
            var_indices = [1, 2, 3]  # X, Y, Z
        
        # Map plane to dimension info
        if plane == 'XY':
            grid_i, grid_j, const_k = I, J, K
        elif plane == 'XZ':
            grid_i, grid_j, const_k = I, K, J
        elif plane == 'YZ':
            grid_i, grid_j, const_k = J, K, I
        else:
            raise ValueError(f'plane must be XY, XZ, or YZ')
        
        if index < 0 or index >= const_k:
            raise ValueError(f'index out of range for plane {plane} (0 to {const_k-1})')
        
        print(f"Extracting {plane} slice at index {index}...")
        print(f"Grid dimensions: {grid_i} x {grid_j} = {grid_i * grid_j} points")
        print(f"Total points in full 3D grid: {I} x {J} x {K} = {N}")
        
        # Pre-compute which 1D indices belong to this slice
        slice_indices = set()
        if plane == 'XY':
            # k = index, vary i and j
            for j in range(J):
                for i in range(I):
                    linear_idx = i + j * I + index * I * J
                    slice_indices.add(linear_idx)
        elif plane == 'XZ':
            # j = index, vary i and k
            for k in range(K):
                for i in range(I):
                    linear_idx = i + index * I + k * I * J
                    slice_indices.add(linear_idx)
        elif plane == 'YZ':
            # i = index, vary j and k
            for k in range(K):
                for j in range(J):
                    linear_idx = index + j * I + k * I * J
                    slice_indices.add(linear_idx)
        
        print(f"Slice contains {len(slice_indices)} points")
        
        data = {self.variables[vi-1] if vi <= len(self.variables) else f'var{vi}': [] 
                for vi in var_indices}
        
        gen = self._float_generator()
        
        # Read all variables and extract slice points
        for var_idx in range(1, len(self.variables) + 1):
            var_name = self.variables[var_idx - 1] if var_idx <= len(self.variables) else f'var{var_idx}'
            
            if var_idx in var_indices:
                print(f"  Reading variable {var_idx} ({var_name})...")
                values_in_slice = [None] * len(slice_indices)
                slice_idx_list = sorted(slice_indices)
                slice_idx_to_output = {si: oi for oi, si in enumerate(slice_idx_list)}
            
            for val_idx in range(N):
                try:
                    val = next(gen)
                except StopIteration:
                    break
                
                if var_idx in var_indices and val_idx in slice_indices:
                    out_idx = slice_idx_to_output[val_idx]
                    values_in_slice[out_idx] = val
            
            if var_idx in var_indices:
                data[var_name] = values_in_slice
        
        print(f"Extracted {len(data)} variables")
        
        result = {
            'plane': plane,
            'index': index,
            'grid_dims': (grid_i, grid_j),
            'data': data,
            'variables': list(data.keys()),
        }
        
        if output_csv:
            import csv
            print(f"Writing to {output_csv}...")
            with open(output_csv, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(data.keys())
                n_points = len(list(data.values())[0]) if data else 0
                for pt_idx in range(n_points):
                    row = [data[var_name][pt_idx] for var_name in data.keys()]
                    writer.writerow(row)
            print(f"Saved to {output_csv}")
        
        return result

if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('file')
    p.add_argument('--var', type=int, default=1, help='1-based variable index')
    p.add_argument('--count', type=int, default=20)
    p.add_argument('--slice', action='store_true', help='Extract a 2D slice')
    p.add_argument('--plane', default='XY', help='Plane: XY, XZ, or YZ')
    p.add_argument('--index', type=int, default=0, help='Slice index')
    p.add_argument('--vars', type=str, default='1,2,3,4,5', help='Comma-separated 1-based variable indices to extract')
    p.add_argument('--output', type=str, help='Output CSV file for slice')
    args = p.parse_args()
    
    r = TecplotLazyReader(args.file)
    r.parse_header()
    print('Parsed header:')
    print(' Variables:', r.variables)
    print(' Zone:', r.zone)
    print(' DATAPACKING:', r.datapacking)
    print(' VARLOCATION:', r.varlocation)
    print(' Data start pos:', r.data_start_pos)
    
    if args.slice:
        var_indices = [int(x) for x in args.vars.split(',')]
        result = r.extract_2d_slice(plane=args.plane, index=args.index, var_indices=var_indices, output_csv=args.output)
        print(f"\nSlice extracted: {result['plane']} at index {result['index']}")
        print(f" Grid: {result['grid_dims']}")
        print(f" Variables: {result['variables']}")
    else:
        print('\nSampling variable #{} (name={}) first {} values:'.format(args.var, r.variables[args.var-1] if r.variables and len(r.variables)>=args.var else 'unknown', args.count))
        sample = r.sample_variable(args.var, args.count)
        for i,v in enumerate(sample):
            print(i, v)
