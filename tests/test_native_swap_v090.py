"""v0.90 — Windows: trocar o núcleo Rust (.dll) que o próprio processo já carregou. Simulado no Linux: o sistema recusa sobrescrever o arquivo «carregado» (PermissionError), mas deixa renomeá-lo.
Que isso funcione numa .dll carregada de verdade no Windows NÃO foi verificado aqui."""
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from openflow import native


class SwapTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.final = self.tmp / "openflow_core.dll"
        self.final.write_bytes(b"old")
        self.src = self.tmp / "openflow_core.dll.new"
        self.src.write_bytes(b"new")
        self.real = os.replace

    def locked_replace(self, a, b):
        if Path(b) == self.final and Path(b).exists():   # o arquivo carregado não pode ser sobrescrito…
            raise PermissionError(13, "acesso negado")
        return self.real(a, b)                            # …mas pode ser renomeado (b não existe mais depois disso)

    def test_a_locked_library_is_renamed_out_of_the_way(self):
        with mock.patch.object(native.os, "replace", self.locked_replace):
            native._swap_in(self.src, self.final)
        self.assertEqual(self.final.read_bytes(), b"new")
        self.assertEqual([p.name for p in self.tmp.iterdir()], ["openflow_core.dll"])   # a antiga foi apagada (aqui nada a segurava)

    def test_the_old_one_that_cannot_be_deleted_is_cleaned_later(self):
        real_unlink = Path.unlink

        def unlink(self_, *a, **k):
            if ".old" in self_.name:
                raise PermissionError(13, "em uso")
            return real_unlink(self_, *a, **k)

        with mock.patch.object(native.os, "replace", self.locked_replace), mock.patch.object(Path, "unlink", unlink):
            native._swap_in(self.src, self.final)
        left = [p.name for p in self.tmp.iterdir() if ".old" in p.name]
        self.assertEqual(len(left), 1)
        self.assertEqual(self.final.read_bytes(), b"new")
        with mock.patch.object(native, "native_dir", return_value=self.tmp), mock.patch.object(native, "_libname", return_value="openflow_core.dll"):
            native._clean_old()
        self.assertEqual([p.name for p in self.tmp.iterdir()], ["openflow_core.dll"])

    def test_a_failure_puts_the_old_library_back(self):
        calls = []

        def replace(a, b):
            calls.append((Path(a).name, Path(b).name))
            if Path(a) == self.src:
                raise PermissionError(13, "nem assim")
            return self.real(a, b)

        with mock.patch.object(native.os, "replace", replace):
            with self.assertRaises(PermissionError):
                native._swap_in(self.src, self.final)
        self.assertEqual(self.final.read_bytes(), b"old")   # sem núcleo é pior que com o antigo

    def test_copy_mode_for_the_compiled_library(self):
        built = self.tmp / "built.dll"
        built.write_bytes(b"compiled")
        real_copy = shutil.copyfile
        state = {"n": 0}

        def copyfile(a, b):
            if Path(b) == self.final and self.final.exists():
                raise PermissionError(13, "acesso negado")
            return real_copy(a, b)

        with mock.patch.object(native.shutil, "copyfile", copyfile), mock.patch.object(native.os, "replace", self.real):
            native._swap_in(built, self.final, copy=True)
        self.assertEqual(self.final.read_bytes(), b"compiled")
        self.assertTrue(built.exists())   # copiar não apaga a origem

    def test_the_normal_case_is_a_plain_replace(self):
        self.final.unlink()
        native._swap_in(self.src, self.final)
        self.assertEqual((self.final.read_bytes(), self.src.exists()), (b"new", False))


if __name__ == "__main__":
    unittest.main()
