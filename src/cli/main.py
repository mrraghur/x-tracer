"""Click-based CLI for X-Tracer."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import click

from .formatters import format_text, format_json, format_dot
from src.vcd.database import _TS_UNITS


def _format_timescale(timescale_fs: int) -> str:
    """Convert timescale in femtoseconds to human-readable string."""
    for unit, fs_per in sorted(_TS_UNITS.items(), key=lambda x: x[1]):
        if timescale_fs % fs_per == 0:
            n = timescale_fs // fs_per
            if n <= 1000:
                return f"{n} {unit}"
    return f"{timescale_fs} fs"


def parse_signal(signal_str: str) -> tuple[str, int]:
    """Parse signal argument into (signal_path, bit_index).

    "tb.dut.result[3]" -> ("tb.dut.result", 3)
    "tb.dut.clk"       -> ("tb.dut.clk", 0)
    """
    m = re.match(r"^(.+)\[(\d+)\]$", signal_str)
    if m:
        return m.group(1), int(m.group(2))
    return signal_str, 0


@click.command()
@click.option("--netlist", "-n", multiple=True, required=True,
              type=click.Path(exists=True),
              help="Verilog netlist file(s)")
@click.option("--vcd", "-v", required=True,
              type=click.Path(exists=True),
              help="VCD file path")
@click.option("--signal", "-s", required=True,
              help='Query signal, e.g. "tb.dut.result[3]" or "tb.dut.clk"')
@click.option("--time", "-t", "query_time", required=True, type=int,
              help="Query time in picoseconds")
@click.option("--format", "-f", "output_format", default="text",
              type=click.Choice(["text", "json", "dot"]),
              help="Output format")
@click.option("--dot-direction", default="forward", show_default=True,
              type=click.Choice(["forward", "backward"]),
              help="DOT edge direction: forward schematic or backward cause tree")
@click.option("--max-depth", default=100, type=int,
              help="Maximum trace depth")
@click.option("--top-module", default=None, type=str,
              help="Top module name (auto-detected if omitted)")
@click.option("--vcd-prefix", default=None, type=str,
              help="VCD hierarchy prefix that maps to netlist top, e.g. 'rjn_top.u_rjn_soc_top'")
@click.option("--fast-parser", is_flag=True, default=False,
              help="Use fast regex-based netlist parser (recommended for large netlists >10MB)")
@click.option("--interactive", "-i", is_flag=True, default=False,
              help="Interactive mode: step through the trace one level at a time")
def cli(netlist, vcd, signal, query_time, output_format, dot_direction, max_depth, top_module, vcd_prefix, fast_parser, interactive):
    """X-Tracer: trace the root cause of X values in gate-level simulations."""
    # Parse signal
    sig_path, sig_bit = parse_signal(signal)

    # Parse netlist
    try:
        netlist_files = [Path(f) for f in netlist]
        # Auto-detect: use fast parser for large files (>10MB total) or if explicitly requested
        total_size = sum(p.stat().st_size for p in netlist_files)
        use_fast = fast_parser or total_size > 10 * 1024 * 1024
        if use_fast:
            from src.netlist import parse_netlist_fast
            click.echo("Using fast regex-based parser", err=True)
            graph = parse_netlist_fast(netlist_files, top_module=top_module)
        else:
            from src.netlist import parse_netlist
            graph = parse_netlist(netlist_files, top_module=top_module)
    except Exception as e:
        click.echo(f"Error parsing netlist: {e}", err=True)
        sys.exit(1)

    # Determine netlist top module name
    netlist_top = top_module or "unknown"
    if netlist_top == "unknown":
        all_netlist_sigs = graph.get_all_signals()
        if all_netlist_sigs:
            netlist_top = next(iter(all_netlist_sigs)).split('.')[0]

    # --- Cone-based VCD loading (avoids OOM on large files) ---
    try:
        from src.vcd import load_vcd_header, load_vcd, load_vcd_fast
        from src.vcd.database import PrefixMappedVCD

        # Step 1: Parse VCD header only (fast — signal names + timescale)
        click.echo("Parsing VCD header ...", err=True)
        vcd_signals, timescale_fs = load_vcd_header(Path(vcd))
        click.echo(f"VCD header: {len(vcd_signals)} signals, timescale {_format_timescale(timescale_fs)}", err=True)

        # Step 2: Map query signal to netlist space for cone computation
        if vcd_prefix:
            # Query signal is in VCD space — map to netlist space for cone computation
            netlist_query_sig = sig_path.replace(vcd_prefix, netlist_top, 1) if sig_path.startswith(vcd_prefix) else sig_path
        else:
            netlist_query_sig = sig_path

        # Step 3: Compute backward cone from netlist
        # Try bus-level signal first, then bit-indexed if bus-level has no drivers
        click.echo(f"Computing backward cone from '{netlist_query_sig}' (max_depth={max_depth}) ...", err=True)
        cone_signals = graph.get_input_cone(netlist_query_sig, max_depth=max_depth)
        if len(cone_signals) <= 1:
            # Bus-level signal not in netlist; try bit-indexed version
            bit_sig = f"{netlist_query_sig}[{sig_bit}]"
            cone_bit = graph.get_input_cone(bit_sig, max_depth=max_depth)
            if len(cone_bit) > len(cone_signals):
                click.echo(f"  (using bit-indexed signal '{bit_sig}')", err=True)
                cone_signals = cone_bit
        click.echo(f"Backward cone: {len(cone_signals)} netlist signals", err=True)

        # Step 4: Map cone signals to VCD names, including per-instance ports
        if vcd_prefix:
            vcd_cone = set()
            for sig in cone_signals:
                if sig.startswith(netlist_top + '.'):
                    vcd_sig = vcd_prefix + sig[len(netlist_top):]
                else:
                    vcd_sig = sig
                if vcd_sig in vcd_signals:
                    vcd_cone.add(vcd_sig)
                elif '[' in vcd_sig:
                    base = vcd_sig[:vcd_sig.rindex('[')]
                    if base in vcd_signals:
                        vcd_cone.add(base)
        else:
            vcd_cone = cone_signals & vcd_signals
            # Also add bus-level VCD names for bit-indexed cone signals
            for sig in cone_signals:
                if '[' in sig and sig not in vcd_signals:
                    base = sig[:sig.rindex('[')]
                    if base in vcd_signals:
                        vcd_cone.add(base)

        # Always include the query signal itself (it's in VCD space)
        if sig_path in vcd_signals:
            vcd_cone.add(sig_path)

        # Add per-instance port signals for gates in the cone.
        # Xcelium VCDs have per-instance signals (e.g. gate.D, gate.Q)
        # that are more accurate than bus-level wires (bus lag issue).
        # Also needed for temporal backtrack (first_x_time on Q port).
        port_count = 0
        for gate in graph._gates.values():
            inst = gate.instance_path
            vcd_inst = inst
            if vcd_prefix and inst.startswith(netlist_top + '.'):
                vcd_inst = vcd_prefix + inst[len(netlist_top):]
            # Check if any of this gate's wire signals are in the cone
            in_cone = False
            for pin in list(gate.inputs.values()) + list(gate.outputs.values()):
                if pin.signal in cone_signals:
                    in_cone = True
                    break
            if not in_cone:
                continue
            # Add per-instance port signals that exist in the VCD.
            # Xcelium VCDs use escaped identifiers (\name) for names with
            # special chars (brackets, etc.). The fast parser strips the
            # backslash, so we try both forms.
            inst_leaf = vcd_inst.rsplit('.', 1)[-1] if '.' in vcd_inst else vcd_inst
            inst_parent = vcd_inst.rsplit('.', 1)[0] if '.' in vcd_inst else ''
            for pname in list(gate.inputs.keys()) + list(gate.outputs.keys()):
                candidates = [
                    f"{vcd_inst}.{pname}",
                    f"{inst_parent}.\\{inst_leaf}.{pname}" if inst_parent else f"\\{inst_leaf}.{pname}",
                ]
                for candidate in candidates:
                    if candidate in vcd_signals:
                        vcd_cone.add(candidate)
                        port_count += 1
                        break
        if port_count > 0:
            click.echo(f"Added {port_count} per-instance port signals", err=True)

        click.echo(f"Loading {len(vcd_cone)} VCD signals (of {len(vcd_signals)} total) ...", err=True)

        # Step 5: Load VCD with only the cone signals filtered
        # Use fast extraction for large VCDs (>100MB) -- extract to mini-VCD first
        vcd_size = Path(vcd).stat().st_size
        _100MB = 100 * 1024 * 1024
        if vcd_size > _100MB:
            click.echo(f"Large VCD ({vcd_size // (1024*1024)} MB) -- using fast extraction", err=True)
            vcd_db = load_vcd_fast(Path(vcd), signals=vcd_cone,
                                   all_signal_names=vcd_signals,
                                   timescale_fs=timescale_fs)
        else:
            vcd_db = load_vcd(Path(vcd), signals=vcd_cone)
    except Exception as e:
        click.echo(f"Error loading VCD: {e}", err=True)
        sys.exit(1)

    # Apply VCD-to-netlist path prefix mapping if specified
    if vcd_prefix:
        click.echo(f"Path mapping: VCD '{vcd_prefix}.*' -> netlist '{netlist_top}.*'", err=True)
        vcd_db = PrefixMappedVCD(vcd_db, vcd_prefix, netlist_top)

    click.echo(f"VCD timescale: {_format_timescale(vcd_db.timescale_fs)}", err=True)

    # Convert user's picosecond time to VCD-native time units
    vcd_time = vcd_db.ps_to_vcd(query_time)
    click.echo(f"Query: {sig_path}[{sig_bit}] @ {query_time} ps (VCD time: {vcd_time})", err=True)

    # Determine the signal path in netlist space (for trace_x)
    # The user provides signal in VCD space; we need netlist space for the tracer
    if vcd_prefix and sig_path.startswith(vcd_prefix + '.'):
        trace_sig = netlist_top + sig_path[len(vcd_prefix):]
    else:
        trace_sig = sig_path

    # Check signal exists in VCD (uses VCD-space via PrefixMappedVCD)
    if not vcd_db.has_signal(trace_sig):
        click.echo(f"Error: signal '{trace_sig}' not found in VCD", err=True)
        sys.exit(1)

    # Check signal is X at query time
    val = vcd_db.get_bit(trace_sig, sig_bit, vcd_time)
    if val != 'x':
        click.echo(
            f"Signal is not X at time {query_time} ps (value={val})",
            err=True,
        )
        sys.exit(1)

    # Run tracer (in netlist space — PrefixMappedVCD handles VCD translation)
    from src.gates import GateModel
    gate_model = GateModel()

    if interactive:
        from src.cli.interactive import run_interactive
        run_interactive(graph, vcd_db, gate_model, trace_sig, sig_bit, vcd_time)
        return

    from src.tracer import trace_x
    try:
        result = trace_x(graph, vcd_db, gate_model,
                         trace_sig, sig_bit, vcd_time,
                         max_depth=max_depth)
    except Exception as e:
        click.echo(f"Error during trace: {e}", err=True)
        sys.exit(1)

    # Format output
    if output_format == "text":
        click.echo(format_text(result))
    elif output_format == "json":
        click.echo(format_json(result))
    elif output_format == "dot":
        click.echo(format_dot(result, direction=dot_direction))


def main():
    cli()


if __name__ == "__main__":
    main()
