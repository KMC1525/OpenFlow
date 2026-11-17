"""v0.82: o nó «Modelo PyTorch/TensorFlow» — aplica a uma imagem um modelo de imagem → imagem (TorchScript, Keras, SavedModel).

As partes de Python puro e o encaixe no nó são testados com um modelo de mentira (uma função do numpy). Com o PyTorch e/ou o TensorFlow instalados (no ambiente de desenvolvimento há os dois, num ambiente à parte) os mesmos testes
rodam também com modelos de verdade, criados na hora: um ampliador 2× em PyTorch (torch.jit.trace) e em Keras (.keras e SavedModel). Que um modelo de terceiros (ESRGAN, etc.) funcione bem NÃO foi verificado."""
import importlib.util
import io
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
from PIL import Image

from openflow.canvas import modelrun as mr
from openflow.canvas.engine import CanvasEngine
from openflow.providers import ProviderError
from openflow.storage import Store

HAS_TORCH = importlib.util.find_spec("torch") is not None
HAS_TF = importlib.util.find_spec("tensorflow") is not None and importlib.util.find_spec("keras") is not None


def png(w=24, h=16, color=(200, 80, 20)):
    b = io.BytesIO()
    Image.new("RGB", (w, h), color).save(b, "PNG")
    return b.getvalue()


def gradient(w=32, h=20):
    x = np.linspace(0, 255, w, dtype="float32")[None, :, None].repeat(h, 0).repeat(3, 2)
    return Image.fromarray(x.astype("uint8"), "RGB")


class FakeRunner(mr.Runner):
    """Um «ampliador 2×» de mentira: repete cada pixel; guarda o que recebeu."""

    def __init__(self, scale=2, layout="NHWC", fixed_hw=None, channels=3, scale_values=1.0):
        self.seen = []

        def infer(x):
            self.seen.append(x)
            y = x if layout == "NHWC" else np.transpose(x, (0, 2, 3, 1))
            y = y.repeat(scale, 1).repeat(scale, 2) * scale_values
            return y if layout == "NHWC" else np.transpose(y, (0, 3, 1, 2))
        super().__init__("keras", Path("fake.keras"), infer, fixed_hw, channels, layout, "Fake")


class PureTests(unittest.TestCase):
    def test_kind_of(self):
        d = Path(tempfile.mkdtemp())
        (d / "sm").mkdir()
        (d / "sm" / "saved_model.pb").write_bytes(b"x")
        for n in ("a.keras", "b.h5", "c.pt", "d.pth", "e.ts", "f.pt2", "tf_model.h5", "model.weights.h5", "w.safetensors", "m.onnx", "x.gguf", "readme.md"):
            (d / n).write_bytes(b"x")
        got = {n: mr.kind_of(d / n) for n in ("a.keras", "b.h5", "c.pt", "d.pth", "e.ts", "f.pt2", "tf_model.h5", "model.weights.h5", "w.safetensors", "m.onnx", "x.gguf", "readme.md", "sm")}
        self.assertEqual(got, {"a.keras": "keras", "b.h5": "keras", "c.pt": "torchscript", "d.pth": "torchscript", "e.ts": "torchscript", "f.pt2": "torchexport", "tf_model.h5": "", "model.weights.h5": "", "w.safetensors": "",
                               "m.onnx": "", "x.gguf": "", "readme.md": "", "sm": "savedmodel"})
        self.assertEqual([mr.framework_of(k) for k in ("keras", "savedmodel", "torchscript", "torchexport", "")], ["tf", "tf", "torch", "torch", ""])

    def test_candidates_prefer_the_obvious_name_then_the_biggest(self):
        d = Path(tempfile.mkdtemp())
        (d / "small.pt").write_bytes(b"x" * 10)
        (d / "big.pt").write_bytes(b"x" * 1000)
        (d / "model.keras").write_bytes(b"x" * 5)
        self.assertEqual([c.name for c in mr.candidates(d)], ["model.keras", "big.pt", "small.pt"])
        self.assertEqual([c.name for c in mr.candidates(d, "torch")], ["big.pt", "small.pt"])
        self.assertEqual([c.name for c in mr.candidates(d, "tf")], ["model.keras"])

    def test_resolve_file_folder_and_the_errors(self):
        d = Path(tempfile.mkdtemp())
        (d / "net.pt").write_bytes(b"x")
        (d / "w.safetensors").write_bytes(b"x")
        self.assertEqual(mr.resolve(str(d / "net.pt")), (d / "net.pt", "torchscript"))
        self.assertEqual(mr.resolve(str(d))[1], "torchscript")                             # pasta: acha o modelo dentro
        with self.assertRaises(ProviderError) as cm:
            mr.resolve("")
        self.assertIn("Escolha o modelo", str(cm.exception))
        with self.assertRaises(ProviderError) as cm:
            mr.resolve(str(d / "w.safetensors"))
        self.assertIn("só tem os PESOS", str(cm.exception))
        with self.assertRaises(ProviderError) as cm:
            mr.resolve(str(d / "net.pt"), "tf")
        self.assertIn("é um modelo PyTorch", str(cm.exception))
        with self.assertRaises(ProviderError) as cm:
            mr.resolve(str(d / "nao-existe.pt"))
        self.assertIn("Não achei o modelo", str(cm.exception))
        empty = Path(tempfile.mkdtemp())
        with self.assertRaises(ProviderError) as cm:
            mr.resolve(str(empty))
        self.assertIn("Não achei", str(cm.exception))

    def test_resolve_a_downloaded_repo_and_a_file_inside_it(self):
        snap = Path(tempfile.mkdtemp())
        (snap / "a.pt").write_bytes(b"x")
        (snap / "sub").mkdir()
        (snap / "sub" / "b.keras").write_bytes(b"x")
        with mock.patch("openflow.canvas.localmodels._snapshot", return_value=snap):
            self.assertEqual(mr.resolve("acme/esrgan")[0].name, "a.pt")
            self.assertEqual(mr.resolve("acme/esrgan::sub/b.keras"), (snap / "sub" / "b.keras", "keras"))
            with self.assertRaises(ProviderError):
                mr.resolve("acme/esrgan::../etc/passwd")
            with self.assertRaises(ProviderError):
                mr.resolve("acme/esrgan::nope.pt")
        with mock.patch("openflow.canvas.localmodels._snapshot", return_value=None):
            with self.assertRaises(ProviderError) as cm:
                mr.resolve("acme/esrgan")
        self.assertIn("ainda não foi baixado", str(cm.exception))

    def test_resolve_a_name_in_the_custom_models_folder(self):
        models = Path(tempfile.mkdtemp())
        (models / "custom").mkdir()
        (models / "custom" / "den.keras").write_bytes(b"x")
        self.assertEqual(mr.resolve("den.keras", "", models)[1], "keras")

    def test_array_roundtrip_in_every_range(self):
        img = gradient()
        for rng in mr.RANGES:
            arr = mr.to_array(img, rng, 3)
            self.assertEqual(arr.shape, (1, 20, 32, 3))
            back = mr.to_image(arr, rng)
            self.assertLessEqual(np.abs(np.asarray(back, dtype="int16") - np.asarray(img, dtype="int16")).max(), 1, rng)
        self.assertEqual(mr.to_array(img, "0-1", 1).shape, (1, 20, 32, 1))
        self.assertEqual(mr.to_array(img, "0-1", 4).shape, (1, 20, 32, 4))

    def test_output_range_is_detected(self):
        self.assertEqual(mr.detect_range(np.array([0, 200.0]), "0-1"), "0-255")
        self.assertEqual(mr.detect_range(np.array([-1.0, 0.9]), "0-1"), "-1-1")
        self.assertEqual(mr.detect_range(np.array([0.0, 0.9]), "0-1"), "0-1")
        img = mr.to_image(np.full((1, 4, 4, 3), -1.0, "float32") * np.array([1, 1, 1]) + np.linspace(0, 2, 4)[None, None, :, None], "auto")
        self.assertEqual(img.size, (4, 4))

    def test_output_shapes(self):
        self.assertEqual(mr.to_image(np.zeros((1, 5, 6, 1), "float32"), "0-1").mode, "L")
        self.assertEqual(mr.to_image(np.zeros((5, 6), "float32"), "0-1").mode, "L")
        self.assertEqual(mr.to_image(np.zeros((1, 5, 6, 4), "float32"), "0-1").mode, "RGBA")
        with self.assertRaises(ProviderError) as cm:
            mr.to_image(np.zeros((1, 5, 6, 7), "float32"), "0-1")
        self.assertIn("1, 3 ou 4 canais", str(cm.exception))

    def test_apply_scales_by_what_the_model_returns(self):
        r = FakeRunner(scale=2)
        out = mr.apply(r, gradient(32, 20))
        self.assertEqual(out.size, (64, 40))
        self.assertAlmostEqual(r.seen[0].max(), 1.0, delta=0.01)                           # 0-1 por padrão
        r = FakeRunner(scale=2, scale_values=255.0)                                        # devolve 0-255: reconhecido sozinho
        self.assertEqual(mr.apply(r, gradient()).getpixel((63, 5))[0], 255)

    def test_apply_with_the_input_range_0_255_and_minus1_1(self):
        r = FakeRunner()
        mr.apply(r, gradient(), rng_in="0-255")
        self.assertAlmostEqual(float(r.seen[0].max()), 255.0, delta=0.5)
        r = FakeRunner()
        mr.apply(r, gradient(), rng_in="-1-1")
        self.assertAlmostEqual(float(r.seen[0].min()), -1.0, delta=0.01)

    def test_channels_first_models_get_transposed_arrays(self):
        r = FakeRunner(layout="NCHW")
        out = mr.apply(r, gradient(32, 20))
        self.assertEqual(r.seen[0].shape, (1, 3, 20, 32))
        self.assertEqual(out.size, (64, 40))

    def test_a_fixed_size_model_gets_the_image_resized(self):
        notes = []
        r = FakeRunner(scale=1, fixed_hw=(16, 24))
        out = mr.apply(r, gradient(32, 20), note=notes.append)
        self.assertEqual(r.seen[0].shape, (1, 16, 24, 3))
        self.assertEqual(out.size, (24, 16))
        self.assertTrue(any("só aceita 24×16" in n for n in notes), notes)

    def test_the_longest_side_is_limited(self):
        notes = []
        r = FakeRunner(scale=1)
        out = mr.apply(r, gradient(200, 100), max_side=50, note=notes.append)
        self.assertEqual(out.size, (50, 25))
        self.assertTrue(any("Reduzi a imagem" in n for n in notes), notes)
        self.assertEqual(mr.apply(FakeRunner(scale=1), gradient(200, 100), max_side=0).size, (200, 100))

    def test_padding_to_a_multiple_is_cropped_back(self):
        r = FakeRunner(scale=2)
        out = mr.apply(r, gradient(30, 18), multiple=8)
        self.assertEqual(r.seen[0].shape[1:3], (24, 32))                                  # 18 → 24 e 30 → 32
        self.assertEqual(out.size, (60, 36))                                               # a sobra é cortada de volta

    def test_tiles_give_the_same_image_as_the_whole_picture(self):
        img = gradient(100, 60)
        whole = mr.apply(FakeRunner(scale=2), img)
        checks, notes = [], []
        tiled = mr.apply(FakeRunner(scale=2), img, tile=32, check=lambda: checks.append(1), note=notes.append)
        self.assertEqual(tiled.size, whole.size)
        self.assertLessEqual(np.abs(np.asarray(tiled, dtype="int16") - np.asarray(whole, dtype="int16")).max(), 1)
        self.assertEqual(len(checks), 4 * 2)                                               # 4×2 blocos; o cancelamento é lido em cada um
        self.assertTrue(any("Bloco 8 de 8" in n for n in notes), notes)

    def test_cancel_stops_between_tiles(self):
        n = []

        def check():
            n.append(1)
            if len(n) == 3:
                raise KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt):
            mr.apply(FakeRunner(), gradient(100, 60), tile=32, check=check)
        self.assertEqual(len(n), 3)

    def test_fingerprint_changes_with_the_file(self):
        d = Path(tempfile.mkdtemp())
        f = d / "m.pt"
        f.write_bytes(b"a")
        a = mr.fingerprint(f)
        f.write_bytes(b"abc")
        self.assertNotEqual(a, mr.fingerprint(f))
        self.assertNotEqual(mr.fingerprint(d), "")


class NodeBase(unittest.TestCase):
    def setUp(self):
        from openflow.canvas import media
        media._LOCAL_CACHE.clear()
        self.store = Store(Path(tempfile.mkdtemp()))
        self.cs = self.store.projects
        self.cid = self.cs.create("modelo")["id"]

    def run_graph(self, params, image=True, wh=(24, 16)):
        nodes = [{"id": "m", "type": "ai_model", "x": 0, "y": 0, "params": params}]
        edges = []
        if image:
            a = self.cs.add_asset(self.cid, png(*wh), "png", "image", name="foto.png", mime="image/png", provider="upload")
            nodes.append({"id": "u", "type": "upload", "x": 0, "y": 0, "params": {"files": [a["id"]]}})
            edges.append({"id": "e", "from": "u", "to": "m", "port": "image"})
        self.cs.save_layout(self.cid, {"nodes": nodes, "edges": edges})
        self.events = []
        CanvasEngine(self.store, self.cid, self.events.append, lambda: False).run(None, True)
        cv = self.cs.get(self.cid)
        return cv, next(n for n in cv["nodes"] if n["id"] == "m")["result"]

    def error(self):
        return next((e.get("message") for e in self.events if e.get("type") == "node" and e.get("id") == "m" and e.get("state") == "error"), None)

    def out_image(self, cv, res):
        a = next(x for x in cv["assets"] if x["id"] == res["assets"][0])
        return Image.open(io.BytesIO(self.cs.asset_path(self.cid, a["file"]).read_bytes()))


class NodeTests(NodeBase):
    def model_file(self, name="up.keras"):
        d = Path(tempfile.mkdtemp())
        (d / name).write_bytes(b"x")
        return str(d / name)

    def test_params_are_normalized(self):
        from openflow.canvas import schema
        p = schema.normalize_params("ai_model", {})
        self.assertEqual(p, {"model": "", "framework": "auto", "range_in": "0-1", "range_out": "auto", "layout": "auto", "channels": 0, "max_side": 1024, "tile": 0, "multiple": 1})
        p = schema.normalize_params("ai_model", {"framework": "x", "range_in": "9", "channels": 2, "max_side": 99999, "tile": -4, "multiple": 0, "layout": "NCHW"})
        self.assertEqual((p["framework"], p["range_in"], p["channels"], p["max_side"], p["tile"], p["multiple"], p["layout"]), ("auto", "0-1", 0, 8192, 0, 1, "NCHW"))
        self.assertIn("ai_model", schema.NODE_TYPES)

    def test_runs_a_keras_model_and_saves_the_image(self):
        path = self.model_file("up.keras")
        runner = FakeRunner(scale=2)
        with mock.patch.object(mr, "load_keras", return_value=runner) as ld:
            cv, res = self.run_graph({"model": path})
        self.assertIsNone(self.error())
        self.assertEqual(res["state"], "done")
        self.assertEqual(self.out_image(cv, res).size, (48, 32))
        self.assertEqual(ld.call_args[0][1], "keras")

    def test_runs_a_torchscript_model_on_the_chosen_device(self):
        path = self.model_file("net.pt")
        runner = FakeRunner(scale=2, layout="NCHW")
        runner.kind = "torchscript"
        with mock.patch.object(mr, "load_torchscript", return_value=runner) as ld, mock.patch("openflow.canvas.media._device", return_value=("cpu", None)):
            cv, res = self.run_graph({"model": path})
        self.assertIsNone(self.error())
        self.assertEqual(ld.call_args[0][1], "cpu")
        self.assertEqual(self.out_image(cv, res).size, (48, 32))

    def test_the_model_stays_loaded_between_runs_and_reloads_when_the_file_changes(self):
        path = self.model_file("up.keras")
        with mock.patch.object(mr, "load_keras", return_value=FakeRunner()) as ld:
            self.run_graph({"model": path})
            self.run_graph({"model": path})
            self.assertEqual(ld.call_count, 1)
            Path(path).write_bytes(b"xyz-changed")
            self.run_graph({"model": path})
            self.assertEqual(ld.call_count, 2)

    def test_the_node_is_stale_when_the_model_file_is_replaced(self):
        path = self.model_file("up.keras")
        with mock.patch.object(mr, "load_keras", return_value=FakeRunner()):
            cv, _ = self.run_graph({"model": path})
            eng = CanvasEngine(self.store, self.cid, lambda e: None, lambda: False)
            canvas = self.cs.get(self.cid)
            node = next(n for n in canvas["nodes"] if n["id"] == "m")
            h1 = eng.node_hash(canvas, node)
            Path(path).write_bytes(b"another model")
            self.assertNotEqual(h1, eng.node_hash(canvas, node))

    def test_clear_errors(self):
        self.run_graph({"model": ""})
        self.assertIn("Escolha o modelo", self.error())
        self.run_graph({"model": self.model_file("up.keras")}, image=False)
        self.assertIn("Ligue uma imagem", self.error())
        self.run_graph({"model": "/nao/existe/m.pt"})
        self.assertIn("Não achei o modelo", self.error())
        with mock.patch.object(mr, "load_keras", side_effect=ProviderError("O Keras não conseguiu carregar «up.keras»: x")):
            self.run_graph({"model": self.model_file("up.keras")})
        self.assertIn("O Keras não conseguiu carregar", self.error())

    def test_a_model_that_fails_explains_how_to_fix_it(self):
        def boom(x):
            raise ValueError("Input 0 is incompatible with layer: expected shape=(None, 64, 64, 1)")
        r = mr.Runner("keras", Path("m.keras"), boom, None, 3, "NHWC", "Keras")
        with mock.patch.object(mr, "load_keras", return_value=r):
            self.run_graph({"model": self.model_file("m.keras")})
        self.assertIn("O modelo falhou ao processar a imagem", self.error())
        self.assertIn("canais", self.error())

    def test_out_of_memory_suggests_tiles(self):
        def boom(x):
            raise RuntimeError("CUDA out of memory. Tried to allocate 2.00 GiB")
        r = mr.Runner("torchscript", Path("m.pt"), boom, None, 3, "NCHW", "TorchScript")
        with mock.patch.object(mr, "load_torchscript", return_value=r), mock.patch("openflow.canvas.media._device", return_value=("cpu", None)):
            self.run_graph({"model": self.model_file("m.pt")})
        self.assertIn("Acabou a memória", self.error())
        self.assertIn("blocos", self.error())

    def test_tiles_and_notes_reach_the_node(self):
        with mock.patch.object(mr, "load_keras", return_value=FakeRunner(scale=1)):
            cv, res = self.run_graph({"model": self.model_file("up.keras"), "max_side": 20, "tile": 32}, wh=(60, 30))
        self.assertIsNone(self.error())
        self.assertEqual(self.out_image(cv, res).size, (20, 10))
        self.assertTrue(any("Reduzi a imagem" in w for w in res.get("warnings", [])) or any("Reduzi a imagem" in str(e) for e in self.events))


@unittest.skipUnless(HAS_TORCH, "sem PyTorch")
class RealTorchTests(NodeBase):
    def make(self, scale=2):
        import torch

        class Up(torch.nn.Module):
            def forward(self, x):
                return torch.nn.functional.interpolate(x, scale_factor=float(scale), mode="nearest")
        d = Path(tempfile.mkdtemp())
        torch.jit.trace(Up(), torch.zeros(1, 3, 8, 8)).save(str(d / "up.pt"))
        return d / "up.pt"

    def test_a_real_torchscript_model_upscales_the_image(self):
        cv, res = self.run_graph({"model": str(self.make())}, wh=(24, 16))
        self.assertIsNone(self.error())
        out = self.out_image(cv, res)
        self.assertEqual(out.size, (48, 32))
        self.assertEqual(out.getpixel((5, 5)), (200, 80, 20))                                  # nearest: a cor (uniforme) passa intacta pelo modelo

    def test_real_tiles_equal_the_whole(self):
        runner = mr.load_torchscript(self.make(), "cpu")
        img = gradient(70, 50)
        whole = mr.apply(runner, img)
        tiled = mr.apply(runner, img, tile=32)
        self.assertEqual(np.asarray(whole).tolist(), np.asarray(tiled).tolist())

    def test_a_torch_export_program_with_dynamic_sizes(self):
        import torch

        class Up(torch.nn.Module):
            def forward(self, x):
                return torch.nn.functional.interpolate(x, scale_factor=2.0, mode="nearest")
        h, w = torch.export.Dim("h", min=4, max=4096), torch.export.Dim("w", min=4, max=4096)
        d = Path(tempfile.mkdtemp())
        torch.export.save(torch.export.export(Up(), (torch.zeros(1, 3, 8, 8),), dynamic_shapes={"x": {2: h, 3: w}}), str(d / "up.pt2"))
        self.assertEqual(mr.resolve(str(d / "up.pt2"))[1], "torchexport")
        runner = mr.load_torchexport(d / "up.pt2", "cpu")
        self.assertIsNone(runner.fixed_hw)
        self.assertEqual(mr.apply(runner, gradient(30, 18)).size, (60, 36))
        cv, res = self.run_graph({"model": str(d / "up.pt2")}, wh=(24, 16))
        self.assertIsNone(self.error())
        self.assertEqual(self.out_image(cv, res).size, (48, 32))

    def test_a_torch_export_program_with_a_fixed_size_resizes_the_image(self):
        import torch

        class Up(torch.nn.Module):
            def forward(self, x):
                return torch.nn.functional.interpolate(x, scale_factor=2.0, mode="nearest")
        d = Path(tempfile.mkdtemp())
        torch.export.save(torch.export.export(Up(), (torch.zeros(1, 3, 8, 8),)), str(d / "fixed.pt2"))
        runner = mr.load_torchexport(d / "fixed.pt2", "cpu")
        self.assertEqual(runner.fixed_hw, (8, 8))
        self.assertEqual(mr.apply(runner, gradient(30, 18)).size, (16, 16))

    def test_a_pickled_model_is_not_loaded(self):
        import torch

        d = Path(tempfile.mkdtemp())
        torch.save(torch.nn.Linear(2, 2), str(d / "pickled.pt"))                               # um pickle de modelo, não um TorchScript
        with self.assertRaises(ProviderError) as cm:
            mr.load_torchscript(d / "pickled.pt", "cpu")
        self.assertIn("torch.jit.trace", str(cm.exception))
        self.assertIn("pickles", str(cm.exception))


@unittest.skipUnless(HAS_TF, "sem TensorFlow/Keras")
class RealKerasTests(NodeBase):
    @classmethod
    def setUpClass(cls):
        from openflow.canvas import frameworks
        frameworks.import_tensorflow()          # a ordem certa (o PyTorch antes): o contrário fecha o programa inteiro (ver frameworks.import_tensorflow)

    def make(self, fixed=False, scale=2, ext=".keras"):
        import keras

        inp = keras.Input((8, 8, 3) if fixed else (None, None, 3))
        x = keras.layers.UpSampling2D(scale)(inp)
        model = keras.Model(inp, x)
        d = Path(tempfile.mkdtemp())
        model.save(str(d / ("up" + ext)))
        return d / ("up" + ext)

    def test_a_real_keras_model_upscales_the_image(self):
        cv, res = self.run_graph({"model": str(self.make())}, wh=(24, 16))
        self.assertIsNone(self.error())
        out = self.out_image(cv, res)
        self.assertEqual(out.size, (48, 32))
        self.assertEqual(out.getpixel((5, 5)), (200, 80, 20))

    def test_a_fixed_input_size_resizes_the_image(self):
        runner = mr.load_keras(self.make(fixed=True), "keras")
        self.assertEqual(runner.fixed_hw, (8, 8))
        notes = []
        out = mr.apply(runner, gradient(30, 20), note=notes.append)
        self.assertEqual(out.size, (16, 16))
        self.assertTrue(notes)

    def test_real_tiles_equal_the_whole(self):
        runner = mr.load_keras(self.make(), "keras")
        img = gradient(70, 50)
        self.assertEqual(np.asarray(mr.apply(runner, img)).tolist(), np.asarray(mr.apply(runner, img, tile=32)).tolist())

    def test_lambda_layers_are_refused(self):
        import keras

        inp = keras.Input((None, None, 3))
        out = keras.layers.Lambda(lambda t: t * 2)(inp)
        d = Path(tempfile.mkdtemp())
        keras.Model(inp, out).save(str(d / "lam.keras"))
        with self.assertRaises(ProviderError) as cm:
            mr.load_keras(d / "lam.keras", "keras")
        self.assertIn("Lambda", str(cm.exception))

    def test_a_multi_input_model_is_refused(self):
        import keras

        a, b = keras.Input((8, 8, 3)), keras.Input((8, 8, 3))
        d = Path(tempfile.mkdtemp())
        keras.Model([a, b], keras.layers.Add()([a, b])).save(str(d / "two.keras"))
        with self.assertRaises(ProviderError) as cm:
            mr.load_keras(d / "two.keras", "keras")
        self.assertIn("UMA imagem", str(cm.exception))

    def test_a_savedmodel_folder_runs(self):
        import keras

        inp = keras.Input((None, None, 3))
        model = keras.Model(inp, keras.layers.UpSampling2D(2)(inp))
        d = Path(tempfile.mkdtemp()) / "sm"
        model.export(str(d))
        self.assertEqual(mr.kind_of(d), "savedmodel")
        runner = mr.load_keras(d, "savedmodel")
        self.assertEqual(mr.apply(runner, gradient(16, 12)).size, (32, 24))


if __name__ == "__main__":
    unittest.main()
