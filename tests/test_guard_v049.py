"""v0.49: proteção do computador — se CPU, RAM ou GPU passam do limite (90%) por alguns segundos enquanto o OpenFlow trabalha, ele para tudo (tarefas, processos filhos e modelos)."""
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from openflow import guard as G
from openflow.jobs import Cancelled, JobManager
from openflow.storage import Store
from tests.helpers import ServerCase


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class FakeApp:
    def __init__(self):
        self.jobs = JobManager()
        self.store = Store(Path(tempfile.mkdtemp()))


def make_guard(**cfg):
    app = FakeApp()
    clock = Clock()
    g = G.Guard(app, sampler=lambda: {"cpu": None, "ram": None, "gpu": None}, now=clock)
    if cfg:
        app.store.save_settings({"performance": {"guard": cfg}})
    return g, app, clock


class NormalizeTests(unittest.TestCase):
    def test_defaults_and_clamping(self):
        self.assertEqual(G.normalize(None), {"enabled": True, "limit": 90, "hold_s": 5, "cpu": True, "ram": True, "gpu": True})
        n = G.normalize({"limit": 5, "hold_s": 999, "enabled": "yes", "cpu": 1, "ram": False})
        self.assertEqual((n["limit"], n["hold_s"], n["enabled"], n["cpu"], n["ram"]), (50, 60, True, True, False))
        self.assertEqual(G.normalize({"limit": 150, "hold_s": 0})["limit"], 99)
        self.assertEqual(G.normalize({"hold_s": 0})["hold_s"], 1)
        self.assertEqual(G.normalize({"limit": True})["limit"], 90)


class DecisionTests(unittest.TestCase):
    def test_a_short_spike_does_not_trip_but_a_sustained_load_does(self):
        g, _, clock = make_guard()
        cfg = G.normalize({})
        hot = {"cpu": 50.0, "ram": 95.0, "gpu": None}
        self.assertIsNone(g.observe(hot, True, cfg))
        clock.t += 3
        self.assertIsNone(g.observe(hot, True, cfg))           # 3 s < 5 s
        clock.t += 1
        g.observe({"cpu": 50.0, "ram": 60.0, "gpu": None}, True, cfg)   # a carga caiu: recomeça
        clock.t += 4
        self.assertIsNone(g.observe(hot, True, cfg))
        clock.t += 5
        r = g.observe(hot, True, cfg)
        self.assertEqual([m["metric"] for m in r["metrics"]], ["ram"])
        self.assertEqual((r["limit"], r["hold_s"]), (90, 5))

    def test_exactly_at_the_limit_counts_and_below_does_not(self):
        g, _, clock = make_guard()
        cfg = G.normalize({"hold_s": 1})
        g.observe({"cpu": 89.9, "ram": None, "gpu": None}, True, cfg)
        clock.t += 2
        self.assertIsNone(g.observe({"cpu": 89.9, "ram": None, "gpu": None}, True, cfg))
        g.observe({"cpu": 90.0, "ram": None, "gpu": None}, True, cfg)
        clock.t += 1
        self.assertEqual(g.observe({"cpu": 90.0, "ram": None, "gpu": None}, True, cfg)["metrics"][0]["metric"], "cpu")

    def test_nothing_happens_when_openflow_is_idle_or_the_guard_or_the_metric_is_off(self):
        g, _, clock = make_guard()
        for _ in range(3):
            clock.t += 10
            self.assertIsNone(g.observe({"cpu": 100.0, "ram": 99.0, "gpu": 99.0}, False, G.normalize({})))   # o OpenFlow está parado: a sobrecarga é de outro programa
        off = G.normalize({"enabled": False})
        clock.t += 10
        self.assertIsNone(g.observe({"cpu": 100.0, "ram": 99.0, "gpu": 99.0}, True, off))
        only_ram = G.normalize({"cpu": False, "gpu": False})
        g.observe({"cpu": 100.0, "ram": 10.0, "gpu": 100.0}, True, only_ram)
        clock.t += 30
        self.assertIsNone(g.observe({"cpu": 100.0, "ram": 10.0, "gpu": 100.0}, True, only_ram))
        self.assertIsNone(g.observe({"cpu": None, "ram": None, "gpu": None}, True, G.normalize({})))   # sem medida: nada a decidir

    def test_a_custom_limit_and_time_are_used(self):
        g, _, clock = make_guard()
        cfg = G.normalize({"limit": 70, "hold_s": 2, "cpu": False, "gpu": False})
        g.observe({"cpu": None, "ram": 75.0, "gpu": None}, True, cfg)
        clock.t += 2
        r = g.observe({"cpu": None, "ram": 75.0, "gpu": None}, True, cfg)
        self.assertEqual((r["limit"], r["metrics"][0]["value"]), (70, 75.0))


def spin(job):
    while not job.cancelled:
        time.sleep(0.02)
    raise Cancelled()


class StopAllTests(unittest.TestCase):
    def test_it_cancels_jobs_kills_children_unloads_models_and_records_the_trip(self):
        g, app, clock = make_guard()
        started = []

        def work(job):
            started.append(1)
            while not job.cancelled:
                time.sleep(0.02)
            raise Cancelled()

        job = app.jobs.start("canvas:x", work)
        while not started:
            time.sleep(0.01)
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        unloaded = []
        with mock.patch.object(G.Guard, "_unload_text", staticmethod(lambda: unloaded.append("t") or True)), mock.patch.object(G.Guard, "_unload_media", staticmethod(lambda: unloaded.append("m") or False)):
            trip = g.stop_all({"metrics": [{"metric": "ram", "value": 94.2, "seconds": 5.0}], "limit": 90})
        for _ in range(100):
            if job.status != "running":
                break
            time.sleep(0.02)
        self.assertEqual(job.status, "cancelled")
        self.assertEqual(job.meta.get("stopped_by"), "guard")
        self.assertTrue(any(e.get("type") == "note" and "memória RAM em 94.2%" in e["message"] for e in job.events))
        child.wait(timeout=5)
        self.assertNotEqual(child.returncode, None)                      # o processo filho foi encerrado
        self.assertEqual(unloaded, ["t", "m"])
        self.assertEqual((trip["stopped"]["jobs"], trip["stopped"]["models"]), (1, 1))
        self.assertGreaterEqual(trip["stopped"]["processes"], 1)
        self.assertEqual((g.last_trip["id"], g.trips), (1, 1))
        # cooldown: logo depois não dispara de novo, mesmo com a carga alta
        g.observe({"cpu": None, "ram": 99.0, "gpu": None}, True, G.normalize({"hold_s": 1}))
        clock.t += 2
        self.assertIsNone(g.observe({"cpu": None, "ram": 99.0, "gpu": None}, True, G.normalize({"hold_s": 1})))
        clock.t += G.COOLDOWN_S
        g.observe({"cpu": None, "ram": 99.0, "gpu": None}, True, G.normalize({"hold_s": 1}))
        clock.t += 2
        self.assertIsNotNone(g.observe({"cpu": None, "ram": 99.0, "gpu": None}, True, G.normalize({"hold_s": 1})))

    def test_tick_end_to_end_with_a_fake_sampler(self):
        g, app, clock = make_guard(hold_s=3)
        job = app.jobs.start("canvas:y", spin)
        g.sampler = lambda: {"cpu": 10.0, "ram": 96.0, "gpu": None}
        with mock.patch.object(G.Guard, "_unload_text", staticmethod(lambda: False)), mock.patch.object(G.Guard, "_unload_media", staticmethod(lambda: False)):
            results = []
            for _ in range(5):
                results.append(g.tick())
                clock.t += 1
        self.assertIsNone(results[0])
        self.assertIsNotNone(next(r for r in results if r))
        for _ in range(100):
            if job.status != "running":
                break
            time.sleep(0.02)
        self.assertEqual(job.status, "cancelled")

    def test_status_reports_metrics_limit_and_support(self):
        g, _, _ = make_guard()
        g.observe({"cpu": 40.0, "ram": 91.0, "gpu": None}, True, G.normalize({"hold_s": 30}))
        s = g.status()
        self.assertEqual((s["enabled"], s["limit"], s["hold_s"]), (True, 90, 5))
        self.assertEqual(s["metrics"]["ram"], 91.0)
        self.assertEqual(s["over"], ["ram"])
        self.assertEqual(s["supported"], {"cpu": True, "ram": True, "gpu": False})


@unittest.skipUnless(sys.platform.startswith("linux"), "/proc só no Linux")
class ProcessTests(unittest.TestCase):
    def test_children_include_grandchildren_and_kill_pids_ends_them(self):
        p = subprocess.Popen(["sh", "-c", "sleep 60 & sleep 60"])
        time.sleep(0.4)
        kids = G.children_of(os.getpid())
        self.assertIn(p.pid, kids)
        self.assertGreaterEqual(len(kids), 2)               # o sh e o sleep dele
        self.assertGreaterEqual(G.kill_pids(kids), 2)
        p.wait(timeout=5)
        time.sleep(0.2)
        self.assertNotIn(p.pid, G.children_of(os.getpid()))


class SamplerTests(unittest.TestCase):
    def test_cpu_percent_from_two_readings(self):
        G._CPU_PREV.clear()
        with mock.patch.object(G, "_cpu_times", side_effect=[(1000.0, 800.0), (1100.0, 810.0)]):
            self.assertIsNone(G.cpu_percent())                # a primeira leitura só marca o começo
            self.assertAlmostEqual(G.cpu_percent(), 90.0, places=1)    # 100 de tempo, 10 ocioso
        G._CPU_PREV.clear()

    def test_ram_percent_uses_total_and_available(self):
        with mock.patch("openflow.native.sys_info", return_value={"ram_total": 16 << 30, "ram_avail": 2 << 30}):
            self.assertAlmostEqual(G.ram_percent(), 87.5, places=1)
        with mock.patch("openflow.native.sys_info", return_value={"ram_total": 0, "ram_avail": 0}):
            self.assertIsNone(G.ram_percent())

    def test_gpu_percent_takes_the_largest_of_vram_and_utilization(self):
        G._GPU_CACHE.update(t=0.0, v=None)
        with mock.patch("openflow.perf.gpu_memory", return_value=(8 << 30, 1 << 30, False)), mock.patch.object(G.shutil, "which", return_value=None):
            self.assertAlmostEqual(G.gpu_percent(), 87.5, places=1)
        G._GPU_CACHE.update(t=0.0, v=None)
        with mock.patch("openflow.perf.gpu_memory", return_value=(0, 0, False)), mock.patch.object(G.shutil, "which", return_value=None):
            self.assertIsNone(G.gpu_percent())
        G._GPU_CACHE.update(t=0.0, v=None)


class ApiTests(ServerCase):
    def test_settings_are_clamped_and_the_status_route_works(self):
        self.c.json("PUT", "/api/settings", {"performance": {"guard": {"limit": 3, "hold_s": 500, "cpu": False, "enabled": "x"}}})
        s, r = self.c.json("GET", "/api/settings")
        g = r["performance"]["guard"]
        self.assertEqual((g["limit"], g["hold_s"], g["cpu"], g["enabled"]), (50, 60, False, True))
        s, st = self.c.json("GET", "/api/guard")
        self.assertEqual(s, 200)
        self.assertEqual((st["limit"], st["hold_s"], st["watch"]["cpu"]), (50, 60, False))
        self.c.json("PUT", "/api/settings", {"performance": {"guard": {"limit": 90, "hold_s": 5, "cpu": True}}})

    def test_saving_other_performance_options_keeps_the_guard(self):
        self.c.json("PUT", "/api/settings", {"performance": {"guard": {"limit": 80}}})
        self.c.json("PUT", "/api/settings", {"performance": {"mode": "light"}})
        self.assertEqual(self.c.json("GET", "/api/settings")[1]["performance"]["guard"]["limit"], 80)
        self.c.json("PUT", "/api/settings", {"performance": {"mode": "auto", "guard": {"limit": 90}}})

    def test_manual_stop_cancels_a_running_job(self):
        s, p = self.c.json("POST", "/api/projects", {"name": "G", "template": "blank"})
        job = self.app.jobs.start("canvas:z", spin)
        with mock.patch.object(G.Guard, "_unload_text", staticmethod(lambda: False)), mock.patch.object(G.Guard, "_unload_media", staticmethod(lambda: False)):
            s, trip = self.c.json("POST", "/api/guard/stop", {})
        self.assertEqual(s, 200)
        self.assertTrue(trip["manual"])
        self.assertGreaterEqual(trip["stopped"]["jobs"], 1)
        for _ in range(100):
            if job.status != "running":
                break
            time.sleep(0.02)
        self.assertEqual(job.status, "cancelled")
        self.assertEqual(self.c.json("GET", "/api/guard")[1]["last_trip"]["manual"], True)


if __name__ == "__main__":
    unittest.main()
