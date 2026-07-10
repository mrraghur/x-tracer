"""Integration tests for the X-Tracer CLI."""

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
CASES_DIR = _PROJECT_ROOT / "tests" / "cases" / "synthetic"
X_TRACER = [sys.executable, str(_PROJECT_ROOT / "x_tracer.py")]


def _run_cli(*args, expect_rc=0) -> subprocess.CompletedProcess:
    """Run the CLI and return the result."""
    result = subprocess.run(
        X_TRACER + list(args),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        universal_newlines=True,
        cwd=str(_PROJECT_ROOT),
    )
    if expect_rc is not None:
        assert result.returncode == expect_rc, (
            f"Expected rc={expect_rc}, got {result.returncode}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
    return result


def _case_args(case_dir, manifest, fmt="text"):
    """Build CLI arguments from a test case manifest."""
    query = manifest["query"]
    return [
        "--netlist", str(case_dir / "netlist.v"),
        "--netlist", str(case_dir / "tb.v"),
        "--vcd", str(case_dir / "sim.vcd"),
        "--signal", query["signal"],
        "--time", str(query["time"]),
        "--format", fmt,
    ]


def _load_manifest(case_dir: Path) -> dict:
    return json.loads((case_dir / "manifest.json").read_text())


# --- Test 1: text format on simple gate case ---

class TestTextFormat:
    def test_simple_gate_text(self):
        case_dir = CASES_DIR / "gates" / "synth_s1_not_1in_xmask1_na"
        manifest = _load_manifest(case_dir)
        result = _run_cli(*_case_args(case_dir, manifest, "text"))
        assert "[" in result.stdout  # has cause_type brackets
        assert "tb.dut" in result.stdout
        assert "t=" in result.stdout


# --- Test 2: json format ---

class TestJsonFormat:
    def test_json_output(self):
        case_dir = CASES_DIR / "gates" / "synth_s1_not_1in_xmask1_na"
        manifest = _load_manifest(case_dir)
        result = _run_cli(*_case_args(case_dir, manifest, "json"))
        data = json.loads(result.stdout)
        assert "signal" in data
        assert "time" in data
        assert "cause_type" in data
        assert "children" in data

    def test_json_has_correct_query(self):
        case_dir = CASES_DIR / "gates" / "synth_s1_and_2in_xmask10_0"
        manifest = _load_manifest(case_dir)
        result = _run_cli(*_case_args(case_dir, manifest, "json"))
        data = json.loads(result.stdout)
        assert data["time"] == manifest["query"]["time"]


# --- Test 3: dot format ---

class TestDotFormat:
    def test_dot_output(self):
        case_dir = CASES_DIR / "gates" / "synth_s1_not_1in_xmask1_na"
        manifest = _load_manifest(case_dir)
        result = _run_cli(*_case_args(case_dir, manifest, "dot"))
        assert "digraph" in result.stdout
        assert "rankdir=LR" in result.stdout
        assert "n1 -> n0" in result.stdout
        assert "type=not" in result.stdout
        assert "tb.<B>dut.y[0]</B>" in result.stdout

    def test_dot_backward_direction(self):
        case_dir = CASES_DIR / "gates" / "synth_s1_not_1in_xmask1_na"
        manifest = _load_manifest(case_dir)
        result = _run_cli(*_case_args(case_dir, manifest, "dot"),
                          "--dot-direction", "backward")
        assert "rankdir=TB" in result.stdout
        assert "n0 -> n1" in result.stdout


# --- Test 4: signal not X ---

class TestErrorCases:
    def test_signal_not_x(self):
        case_dir = CASES_DIR / "gates" / "synth_s1_and_2in_xmask01_0"
        manifest = _load_manifest(case_dir)
        result = _run_cli(
            "--netlist", str(case_dir / "netlist.v"),
            "--netlist", str(case_dir / "tb.v"),
            "--vcd", str(case_dir / "sim.vcd"),
            "--signal", manifest["query"]["signal"],
            "--time", "0",
            expect_rc=1,
        )
        assert "not X" in result.stderr or "value=" in result.stderr

    def test_signal_not_found(self):
        case_dir = CASES_DIR / "gates" / "synth_s1_not_1in_xmask1_na"
        manifest = _load_manifest(case_dir)
        result = _run_cli(
            "--netlist", str(case_dir / "netlist.v"),
            "--netlist", str(case_dir / "tb.v"),
            "--vcd", str(case_dir / "sim.vcd"),
            "--signal", "nonexistent.signal",
            "--time", "30000",
            expect_rc=1,
        )
        assert "not found" in result.stderr


# --- Test 6: multiple netlist files ---

class TestMultipleNetlists:
    def test_two_netlist_files(self):
        case_dir = CASES_DIR / "gates" / "synth_s1_not_1in_xmask1_na"
        manifest = _load_manifest(case_dir)
        result = _run_cli(*_case_args(case_dir, manifest, "text"))
        assert result.returncode == 0
        assert "tb.dut" in result.stdout


# --- Test 7: structural case ---

class TestStructural:
    def test_bus_encoder(self):
        case_dir = CASES_DIR / "structural" / "bus_encoder_w4"
        manifest = _load_manifest(case_dir)
        result = _run_cli(*_case_args(case_dir, manifest, "text"))
        inj_target = manifest["expected"]["injection_target"]
        assert inj_target in result.stdout

    def test_reconverge(self):
        case_dir = CASES_DIR / "structural" / "reconverge_d2"
        manifest = _load_manifest(case_dir)
        result = _run_cli(*_case_args(case_dir, manifest, "json"))
        data = json.loads(result.stdout)
        assert data["cause_type"] in (
            "x_propagation", "primary_input", "x_injection",
            "unknown_cell",
        )


# --- Test 8: multibit case ---

class TestMultibit:
    def test_bit_slice(self):
        case_dir = CASES_DIR / "multibit" / "bit_slice_w16_b0_select"
        manifest = _load_manifest(case_dir)
        result = _run_cli(*_case_args(case_dir, manifest, "text"))
        assert result.returncode == 0


# --- Test 9: bulk test across categories ---

def _collect_bulk_cases():
    """Collect 10+ cases across all categories."""
    cases = []
    gates_dir = CASES_DIR / "gates"
    if gates_dir.exists():
        for d in sorted(gates_dir.iterdir())[:5]:
            cases.append(d)
    struct_dir = CASES_DIR / "structural"
    if struct_dir.exists():
        for name in ["bus_encoder_w4", "reconverge_d2", "reconverge_d4"]:
            d = struct_dir / name
            if d.exists():
                cases.append(d)
    multi_dir = CASES_DIR / "multibit"
    if multi_dir.exists():
        for name in ["bit_slice_w16_b0_select", "partial_bus_and_w4", "partial_bus_or_w4"]:
            d = multi_dir / name
            if d.exists():
                cases.append(d)
    return cases


_BULK_CASES = _collect_bulk_cases()


class TestBulk:
    @pytest.mark.parametrize("case_dir", _BULK_CASES,
                             ids=[c.name for c in _BULK_CASES])
    def test_cli_exit_0_and_injection_in_output(self, case_dir):
        manifest = _load_manifest(case_dir)
        result = _run_cli(*_case_args(case_dir, manifest, "text"))
        inj_target = manifest["expected"]["injection_target"]
        m = re.match(r'^(.+)\[(\d+)\]$', inj_target)
        if m:
            inj_sig = m.group(1)
        else:
            inj_sig = inj_target
        assert inj_sig in result.stdout, (
            f"Injection target signal '{inj_sig}' not found in output:\n{result.stdout}"
        )


# --- Test 10: --fast-parser flag ---

class TestFastParserFlag:
    """Verify the --fast-parser flag activates the fast regex-based parser.

    Note: The fast parser handles module instantiations but not Verilog
    primitives (and, or, not, buf). Test cases using primitives will fail
    to trace but should still show the stderr message.
    """

    def test_fast_parser_stderr_message(self):
        """Verify --fast-parser flag is recognized and reported."""
        case_dir = CASES_DIR / "gates" / "synth_s1_not_1in_xmask1_na"
        manifest = _load_manifest(case_dir)
        result = _run_cli(*_case_args(case_dir, manifest, "text"),
                          "--fast-parser", expect_rc=None)
        assert "Using fast regex-based parser" in result.stderr

    def test_fast_parser_on_structural_case(self):
        case_dir = CASES_DIR / "structural" / "bus_encoder_w4"
        manifest = _load_manifest(case_dir)
        result = _run_cli(*_case_args(case_dir, manifest, "text"), "--fast-parser")
        assert result.returncode == 0
        assert "Using fast regex-based parser" in result.stderr


# --- Test 12: VCD timescale display ---

class TestVCDTimescaleDisplay:
    """Verify stderr contains VCD timescale information."""

    def test_timescale_in_stderr(self):
        case_dir = CASES_DIR / "gates" / "synth_s1_not_1in_xmask1_na"
        manifest = _load_manifest(case_dir)
        result = _run_cli(*_case_args(case_dir, manifest, "text"))
        assert "VCD timescale:" in result.stderr

    def test_timescale_has_unit(self):
        case_dir = CASES_DIR / "gates" / "synth_s1_not_1in_xmask1_na"
        manifest = _load_manifest(case_dir)
        result = _run_cli(*_case_args(case_dir, manifest, "text"))
        assert re.search(r"VCD timescale:\s+\d+\s+(fs|ps|ns|us|ms|s)", result.stderr)


# --- Test 13: query time display ---

class TestQueryTimeDisplay:
    """Verify stderr contains the query information with ps and VCD time."""

    def test_query_message_in_stderr(self):
        case_dir = CASES_DIR / "gates" / "synth_s1_not_1in_xmask1_na"
        manifest = _load_manifest(case_dir)
        result = _run_cli(*_case_args(case_dir, manifest, "text"))
        assert "Query:" in result.stderr
        assert "ps" in result.stderr
        assert "VCD time:" in result.stderr

    def test_query_shows_correct_time(self):
        case_dir = CASES_DIR / "gates" / "synth_s1_not_1in_xmask1_na"
        manifest = _load_manifest(case_dir)
        query_time = manifest["query"]["time"]
        result = _run_cli(*_case_args(case_dir, manifest, "text"))
        assert f"{query_time} ps" in result.stderr


# --- Test 14: --vcd-prefix flag ---

class TestVCDPrefix:
    """Test --vcd-prefix for hierarchy remapping between netlist and VCD."""

    def test_vcd_prefix_with_temp_files(self, tmp_path):
        """Create netlist with module 'top' and VCD with 'tb.dut.' prefix."""
        netlist_file = tmp_path / "netlist.v"
        netlist_file.write_text(
            "`timescale 1ns/1ps\n"
            "module top (y, a);\n"
            "  output y;\n  input a;\n"
            "  not g0 (y, a);\nendmodule\n"
        )
        vcd_file = tmp_path / "sim.vcd"
        vcd_file.write_text(
            "$date\n  Mon Mar 16 12:00:00 2026\n$end\n"
            "$version\n  Icarus Verilog\n$end\n"
            "$timescale\n  1ps\n$end\n"
            "$scope module tb $end\n"
            "$scope module dut $end\n"
            "$var wire 1 ! a $end\n"
            "$var wire 1 \" y $end\n"
            "$upscope $end\n$upscope $end\n"
            "$enddefinitions $end\n"
            "#0\n$dumpvars\n0!\n1\"\n$end\n"
            "#10000\nx!\nx\"\n#30000\n"
        )
        result = _run_cli(
            "--netlist", str(netlist_file),
            "--vcd", str(vcd_file),
            "--signal", "top.y[0]",
            "--time", "30000",
            "--format", "text",
            "--vcd-prefix", "tb.dut",
            "--top-module", "top",
        )
        assert result.returncode == 0
        assert "Path mapping:" in result.stderr
        assert "top" in result.stdout

    def test_vcd_prefix_stderr_shows_mapping(self, tmp_path):
        """Verify stderr shows the path mapping message."""
        netlist_file = tmp_path / "netlist.v"
        netlist_file.write_text(
            "`timescale 1ns/1ps\n"
            "module top (y, a);\n"
            "  output y;\n  input a;\n"
            "  not g0 (y, a);\nendmodule\n"
        )
        vcd_file = tmp_path / "sim.vcd"
        vcd_file.write_text(
            "$date\n  Mon Mar 16 12:00:00 2026\n$end\n"
            "$version\n  Icarus Verilog\n$end\n"
            "$timescale\n  1ps\n$end\n"
            "$scope module tb $end\n"
            "$scope module dut $end\n"
            "$var wire 1 ! a $end\n"
            "$var wire 1 \" y $end\n"
            "$upscope $end\n$upscope $end\n"
            "$enddefinitions $end\n"
            "#0\n$dumpvars\n0!\n1\"\n$end\n"
            "#10000\nx!\nx\"\n#30000\n"
        )
        result = _run_cli(
            "--netlist", str(netlist_file),
            "--vcd", str(vcd_file),
            "--signal", "top.y[0]",
            "--time", "30000",
            "--format", "text",
            "--vcd-prefix", "tb.dut",
            "--top-module", "top",
        )
        assert "Path mapping: VCD 'tb.dut.*' -> netlist 'top.*'" in result.stderr
