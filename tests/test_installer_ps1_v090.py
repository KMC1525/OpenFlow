"""v0.90 — install.ps1 (Windows): o que dá para provar SEM o Windows, rodando o PowerShell (pwsh) de verdade: o arquivo é lido sem erro de sintaxe, `Find-Python` devolve um array mesmo com um só
candidato, o atalho `flow.cmd` não carrega o caminho do usuário (acentos) e o Path do usuário é acrescido sem perder as entradas «%VARIAVEIS%». Pulado se não há `pwsh` (o CI do GitHub tem em todos os sistemas).
Que o instalador rode inteiro num Windows de verdade NÃO foi verificado aqui (só o CI do GitHub o faz)."""
import json
import os
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PS1 = ROOT / "install.ps1"
PWSH = os.environ.get("OPENFLOW_PWSH") or shutil.which("pwsh")


def run_pwsh(script: str, timeout: int = 120):
    env = {**os.environ, "DOTNET_SYSTEM_GLOBALIZATION_INVARIANT": "1", "POWERSHELL_TELEMETRY_OPTOUT": "1"}
    r = subprocess.run([PWSH, "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True, text=True, timeout=timeout, env=env)
    return r


PRELUDE = r"""
$ErrorActionPreference = 'Stop'
$tokens = $null; $errs = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile('%s', [ref]$tokens, [ref]$errs)
if ($errs.Count -gt 0) { Write-Output ('PARSE: ' + ($errs | ForEach-Object { $_.Message }) -join '; '); exit 3 }
foreach ($f in $ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] }, $true)) {
  if ($f.Name -in @('Find-Python', 'Same-Dir', 'Merge-PathEntry')) { . ([scriptblock]::Create($f.Extent.Text)) }
}
$ErrorActionPreference = 'Continue'
""" % str(PS1).replace("'", "''")


@unittest.skipUnless(PWSH, "sem pwsh (PowerShell)")
class InstallPs1Tests(unittest.TestCase):
    def test_the_script_parses(self):
        r = run_pwsh(PRELUDE + "Write-Output 'ok'")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("ok", r.stdout)

    def test_find_python_returns_an_array_even_with_a_single_candidate(self):
        # sem o «py»: o único candidato que funciona é «python» (Python da Microsoft Store, conda, Chocolatey…)
        script = PRELUDE + r"""
function py { $global:LASTEXITCODE = 1 }
function python { $global:LASTEXITCODE = 0 }
function python3 { $global:LASTEXITCODE = 1 }
$r = Find-Python
[pscustomobject]@{ isArray = ($r -is [array]); count = @($r).Count; first = $r[0] } | ConvertTo-Json -Compress
"""
        r = run_pwsh(script)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        got = json.loads(r.stdout.strip().splitlines()[-1])
        self.assertEqual(got, {"isArray": True, "count": 1, "first": "python"})   # antes: string «python» e $py[0] = «p»

    def test_find_python_with_the_launcher_keeps_its_argument(self):
        script = PRELUDE + r"""
function py { $global:LASTEXITCODE = 0 }
$r = Find-Python
[pscustomobject]@{ count = @($r).Count; first = $r[0]; second = $r[1] } | ConvertTo-Json -Compress
"""
        r = run_pwsh(script)
        self.assertEqual(json.loads(r.stdout.strip().splitlines()[-1]), {"count": 2, "first": "py", "second": "-3"})

    def test_find_python_is_null_when_nothing_works(self):
        script = PRELUDE + r"""
function py { $global:LASTEXITCODE = 9009 }
function python { $global:LASTEXITCODE = 9009 }
function python3 { $global:LASTEXITCODE = 9009 }
$r = Find-Python
if ($null -eq $r) { 'null' } else { 'not null' }
"""
        self.assertEqual(run_pwsh(script).stdout.strip().splitlines()[-1], "null")

    def test_the_path_keeps_entries_with_variables_and_adds_the_folder_once(self):
        script = PRELUDE + r"""
$env:OPENFLOW_T = '/opt/t'
$raw = '%OPENFLOW_T%/bin;C:\Windows;'
$dir = 'C:\Users\Jo' + [char]0xE3 + 'o\AppData\Local\OpenFlow\bin'
$once = Merge-PathEntry $raw $dir
$twice = Merge-PathEntry $once $dir
$viaVar = Merge-PathEntry '%OPENFLOW_T%\bin' '/opt/t\bin'
[pscustomobject]@{ once = $once; twice = ($null -eq $twice); viaVar = ($null -eq $viaVar); empty = (Merge-PathEntry $null 'X') } | ConvertTo-Json -Compress
"""
        r = run_pwsh(script)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        got = json.loads(r.stdout.strip().splitlines()[-1])
        self.assertTrue(got["once"].startswith("%OPENFLOW_T%/bin;C:\\Windows;C:\\Users\\Jo"), got)   # a variável continua sendo variável
        self.assertTrue(got["twice"])                  # já estava: nada a gravar
        self.assertTrue(got["viaVar"])                 # a mesma pasta escrita com a variável também conta como «já está»
        self.assertEqual(got["empty"], "X")            # Path vazio de uma conta nova


class InstallPs1TextTests(unittest.TestCase):
    """Verificações de texto: valem em qualquer sistema, sem o PowerShell."""

    def setUp(self):
        self.src = PS1.read_text(encoding="utf-8")

    def test_the_cmd_shim_has_no_absolute_user_path(self):
        m = re.search(r"Set-Content[^\n]*\$shim[^\n]*", self.src)
        self.assertIsNotNone(m)
        self.assertIn("%~dp0", m.group(0))
        self.assertNotIn("$venv", m.group(0))   # um caminho absoluto gravado em ASCII perdia os acentos do nome do usuário

    def test_the_user_path_is_not_rewritten_with_the_expanded_value(self):
        self.assertNotIn("SetEnvironmentVariable('Path', (($userParts", self.src)
        self.assertIn("DoNotExpandEnvironmentNames", self.src)

    def test_a_single_element_array_is_not_returned_bare(self):
        self.assertRegex(self.src, r"return ,@\(@\(\$exe\) \+ \$args0\)")


class CiWorkflowTests(unittest.TestCase):
    def test_the_workflows_are_valid_yaml(self):
        try:
            import yaml  # type: ignore
        except ImportError:
            self.skipTest("sem PyYAML")
        for f in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
            data = yaml.safe_load(f.read_text(encoding="utf-8"))   # o ci.yml tinha «numpy: os» num nome sem aspas: YAML inválido, e o GitHub nem criava os jobs
            self.assertTrue(data.get("jobs"), f.name)


if __name__ == "__main__":
    unittest.main()
