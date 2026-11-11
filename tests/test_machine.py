"""The machine profile (owner, 2026-11-04): Nemo on a desktop with a GPU,
while the laptop version keeps working exactly as before."""
from __future__ import annotations

import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo import machine, modes
from nemo.config import Config

ROOT = Path(__file__).resolve().parent.parent
RTX3050 = (machine.Gpu("NVIDIA GeForce RTX 3050 OEM", 8192),)


def cfg_with(machine_setting=None) -> Config:
    cfg = Config.load(Path("/nonexistent"))
    if machine_setting:
        cfg.data["machine"] = machine_setting
    return cfg


class TestChoosingTheProfile(unittest.TestCase):
    def detect(self, cards, engine="C:/Nemo/engine-cuda/llama-server.exe"):
        with mock.patch.object(machine, "gpus", return_value=cards), \
             mock.patch.object(machine, "cuda_engine", return_value=engine):
            return machine.detect()

    def test_the_sandbox_runs_every_test_as_the_laptop(self):
        self.assertEqual(os.environ.get("NEMO_MACHINE"), "laptop")
        self.assertEqual(machine.profile(cfg_with())[0], machine.LAPTOP)

    def test_no_nvidia_card_is_the_laptop(self):
        self.assertEqual(self.detect(())[0], machine.LAPTOP)

    def test_a_card_too_small_for_the_design_model_is_the_laptop(self):
        kind, why = self.detect((machine.Gpu("GeForce GTX 1650", 4096),))
        self.assertEqual(kind, machine.LAPTOP)
        self.assertIn("4096", why)

    def test_a_big_enough_card_without_the_cuda_engine_says_so(self):
        kind, why = self.detect(RTX3050, engine=None)
        self.assertEqual(kind, machine.LAPTOP)
        self.assertIn("NemoDoc", why)

    def test_a_big_enough_card_with_the_engine_is_the_desktop(self):
        self.assertEqual(self.detect(RTX3050)[0], machine.DESKTOP)

    def test_config_forces_either_and_the_environment_wins(self):
        with mock.patch.dict(os.environ, {"NEMO_MACHINE": ""}):
            with mock.patch.object(machine, "detect", side_effect=AssertionError("not asked")):
                self.assertEqual(machine.profile(cfg_with("desktop"))[0], "desktop")
                self.assertEqual(machine.profile(cfg_with("laptop"))[0], "laptop")
        with mock.patch.dict(os.environ, {"NEMO_MACHINE": "laptop"}):
            self.assertEqual(machine.profile(cfg_with("desktop"))[0], "laptop")

    def test_a_misspelt_setting_is_auto_not_a_crash(self):
        with mock.patch.dict(os.environ, {"NEMO_MACHINE": ""}):
            self.assertEqual(machine.setting(cfg_with("Destkop")), "auto")


class TestTheModeTables(unittest.TestCase):
    def test_the_laptop_never_reads_the_desktop_table(self):
        cfg = cfg_with()
        laptop = {n: cfg.mode(n) for n in ("design", "build", "talk", "tiny")}
        cfg.data["modes_desktop"] = {n: {"model": "WRONG"} for n in laptop}
        with mock.patch.dict(os.environ, {"NEMO_MACHINE": "laptop"}):
            self.assertEqual({n: cfg.mode(n) for n in laptop}, laptop)
            self.assertFalse(any(s.get("gpu") for s in laptop.values()))

    def test_the_desktop_reads_its_own_table(self):
        with mock.patch.dict(os.environ, {"NEMO_MACHINE": "desktop"}):
            design = cfg_with().mode("design")
        self.assertEqual((design["model"], design["ctx"], design["gpu"]), ("qwen3-8b", 16384, True))

    def test_a_mode_the_desktop_table_lacks_falls_back(self):
        cfg = cfg_with()
        cfg.data["modes_windows"]["odd"] = cfg.data["modes"]["odd"] = {"model": "m", "ram_mb": 1}
        with mock.patch.dict(os.environ, {"NEMO_MACHINE": "desktop"}):
            self.assertEqual(cfg.mode("odd")["model"], "m")

    def test_every_desktop_mode_is_measured_and_fits_the_card_it_was_measured_on(self):
        for name, spec in Config.load(Path("/nonexistent")).get("modes_desktop").items():
            with self.subTest(name):
                self.assertTrue(spec["gpu"])
                self.assertLessEqual(spec["vram_mb"] + modes.VRAM_MARGIN_MIB, 8192)
                self.assertLessEqual(spec["vram_mb"], machine.DESKTOP_MIN_VRAM_MIB)


class TestStartingOnTheGpu(unittest.TestCase):
    def start(self, free_vram=7590,          # an idle RTX 3050 (8192 - 602 in use)
               engine="C:/Nemo/engine-cuda/llama-server.exe", force=False):
        cfg = cfg_with()
        state = Path(tempfile.mkdtemp()) / "mode.pid"
        popen = mock.Mock(return_value=mock.Mock(pid=4242, poll=lambda: None))
        with mock.patch.dict(os.environ, {"NEMO_MACHINE": "desktop"}), \
             mock.patch.object(modes, "STATE", state), \
             mock.patch.object(modes, "mem_available_mb", return_value=8000), \
             mock.patch.object(machine, "gpu_free_mib", return_value=free_vram), \
             mock.patch.object(modes, "gpu_engine_path", return_value=engine), \
             mock.patch.object(modes, "engine_path", return_value="CPU-ENGINE"), \
             mock.patch.object(modes, "llama_binary_runs", return_value=(True, "")), \
             mock.patch.object(modes, "model_path", return_value=Path("qwen3-8b.gguf")), \
             mock.patch.object(modes, "stop"), \
             mock.patch("subprocess.run", return_value=mock.Mock(stdout="", stderr="")), \
             mock.patch("subprocess.Popen", popen), \
             mock.patch.object(modes, "_wait_ready", return_value=True):
            ok, msg = modes.start(cfg, "design", force=force)
        return ok, msg, (popen.call_args[0][0] if popen.called else None)

    def test_every_layer_on_the_gpu_with_the_cuda_engine_and_no_mapping(self):
        ok, msg, cmd = self.start()
        self.assertTrue(ok, msg)
        self.assertEqual(cmd[0], "C:/Nemo/engine-cuda/llama-server.exe")
        self.assertEqual(cmd[cmd.index("-ngl") + 1], "99")
        self.assertEqual(cmd[cmd.index("--load-mode") + 1], "none")
        self.assertEqual(cmd[cmd.index("-c") + 1], "16384")

    def test_too_little_free_on_the_card_is_refused_before_anything_starts(self):
        ok, msg, cmd = self.start(free_vram=3000)
        self.assertFalse(ok)
        self.assertIsNone(cmd)
        self.assertIn("7300 MiB", msg)          # 7000 for the model + the margin
        self.assertIn("3000", msg)

    def test_force_starts_it_anyway(self):
        ok, msg, cmd = self.start(free_vram=3000, force=True)
        self.assertTrue(ok, msg)

    def test_no_cuda_engine_says_what_to_do_and_never_falls_to_the_cpu_one(self):
        ok, msg, cmd = self.start(engine=None)
        self.assertFalse(ok)
        self.assertIsNone(cmd)
        self.assertIn("NemoDoc", msg)
        self.assertIn("machine: laptop", msg)

    def test_the_laptop_start_has_no_gpu_flags(self):
        cfg = cfg_with()
        state = Path(tempfile.mkdtemp()) / "mode.pid"
        popen = mock.Mock(return_value=mock.Mock(pid=4242, poll=lambda: None))
        with mock.patch.object(modes, "STATE", state), \
             mock.patch.object(modes, "mem_available_mb", return_value=8000), \
             mock.patch.object(modes, "engine_path", return_value="CPU-ENGINE"), \
             mock.patch.object(modes, "llama_binary_runs", return_value=(True, "")), \
             mock.patch.object(modes, "model_path", return_value=Path("qwen3-4b.gguf")), \
             mock.patch.object(modes, "stop"), \
             mock.patch("subprocess.run", return_value=mock.Mock(stdout="", stderr="")), \
             mock.patch("subprocess.Popen", popen), \
             mock.patch.object(modes, "_wait_ready", return_value=True):
            ok, msg = modes.start(cfg, "design")
        self.assertTrue(ok, msg)
        cmd = popen.call_args[0][0]
        self.assertEqual(cmd[0], "CPU-ENGINE")
        self.assertNotIn("-ngl", cmd)
        self.assertNotIn("--load-mode", cmd)


class TestTheInstallerFetchesTheSameEngine(unittest.TestCase):
    def test_nemodoc_pins_what_machine_py_pins(self):
        for base in (ROOT, ROOT / "install" / "windows"):
            if (base / "NemoDoc.ps1").exists():
                text = (base / "NemoDoc.ps1").read_text(encoding="utf-8")
                break
        else:
            self.skipTest("NemoDoc.ps1 not in this layout")
        block = text[text.index("$CudaFiles = @("):text.index("$CudaFiles = @(") + 600]
        pinned = set(re.findall(r'file = "([^"]+)"; sha256 = "([0-9a-f]{64})"; bytes = (\d+)', block))
        self.assertEqual(pinned, {(f, h, str(b)) for f, b, h in machine.CUDA_ENGINE})
        self.assertIn("$NvidiaMiB -ge 7000", text)
        self.assertEqual(machine.DESKTOP_MIN_VRAM_MIB, 7000)


class TestTheDoctorDescribesThisMachine(unittest.TestCase):
    def run_doctor(self, flags, cards=(), kind=("laptop", "test")):
        from nemo import doctor
        with mock.patch.object(doctor, "cpu_flags", return_value=set(flags)), \
             mock.patch.object(doctor, "cpu_model", return_value="cpu"), \
             mock.patch.object(doctor, "cpu_threads", return_value=4), \
             mock.patch.object(doctor, "display_adapter", return_value=("NVIDIA GeForce RTX 3050", "1")), \
             mock.patch.object(doctor, "basic_display_adapter", return_value=False), \
             mock.patch.object(doctor, "mem_total_mb", return_value=16228), \
             mock.patch.object(doctor, "mem_available_mb", return_value=9000), \
             mock.patch.object(doctor, "memory_sticks", return_value=["8 GB", "8 GB"]), \
             mock.patch.object(doctor, "llama_binary_runs", return_value=(True, "ok")), \
             mock.patch("nemo.machine.gpus", return_value=cards), \
             mock.patch("nemo.machine.profile", return_value=kind), \
             mock.patch("nemo.machine.cuda_engine", return_value="C:/Nemo/engine-cuda/llama-server.exe"), \
             mock.patch("nemo.platform_probe.find_tool", return_value=None):
            return "\n".join(f.line() for f in doctor.run())

    def test_the_laptops_facts_are_not_said_of_a_modern_cpu(self):
        text = self.run_doctor({"sse4_2", "avx", "avx2"}, RTX3050, ("desktop", "RTX"))
        for laptop_only in ("Sandy Bridge", "Fujitsu", "fourteen-year-old", "2nd-gen Core"):
            self.assertNotIn(laptop_only, text)
        self.assertIn("Machine profile: desktop", text)
        self.assertIn("The models run on it", text)

    def test_the_laptop_still_hears_them(self):
        text = self.run_doctor({"sse4_2"})
        self.assertIn("Sandy Bridge", text)
        self.assertIn("Fujitsu", text)
        self.assertIn("Machine profile: laptop", text)


if __name__ == "__main__":
    unittest.main()
