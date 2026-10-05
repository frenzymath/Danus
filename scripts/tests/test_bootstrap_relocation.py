"""Offline bootstrap relocation tests, including a copy with its original intact."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]

class BootstrapRelocationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="relocation-test-", dir=ROOT)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "deployment"
        for folder in ("scripts", "config", "runtime/venv", "runtime/node22/bin",
                       "runtime/codex-npm/node_modules/@openai/codex/bin"):
            (self.root / folder).mkdir(parents=True)
        for name in ("bootstrap.sh", "env.sh", "detect-toolchain.sh"):
            source = ROOT / "scripts" / name
            if source.exists():
                shutil.copyfile(source, self.root / "scripts" / name)
        self.host = Path(self.tmp.name) / "host tools"
        self.host.mkdir()
        # Existing local tools work with both upstream and host-reuse bootstrap.
        for name, body in (("node", "echo v22.14.0"), ("npm", "exit 91")):
            tool = self.root / "runtime/node22/bin" / name
            tool.write_text("#!/bin/sh\n" + body + "\n")
            tool.chmod(0o755)
        (self.root / "runtime/codex-npm/node_modules/@openai/codex/bin/codex.js").touch()
        for name, body in (("curl", "exit 92"), ("uname", "echo Linux")):
            tool = self.host / name
            tool.write_text("#!/bin/sh\n" + body + "\n")
            tool.chmod(0o755)
        self.env = {"PATH": f"{self.host}:/usr/bin:/bin", "HOME": str(self.root)}

    def bootstrap(self):
        return subprocess.run(["/bin/bash", "scripts/bootstrap.sh"], cwd=self.root,
                              env=self.env, text=True, capture_output=True,
                              check=True).stdout

    def real_venv_fixture(self):
        """Real relocatable Python fixture; fake pip never installs/downloads."""
        package = self.root / "danus"
        package.mkdir()
        (package / "__init__.py").write_text("")
        (package / "_mcp.py").write_text("FastMCP = object\n")
        builder = self.host / "python3"
        builder.write_text("#!" + sys.executable + "\n" + r'''import pathlib, sys, venv
if sys.argv[1] == "-c":
    print(pathlib.Path(__file__).resolve())
else:
    assert sys.argv[1:3] == ["-m", "venv"]
    dest = pathlib.Path(sys.argv[3])
    venv.EnvBuilder(with_pip=False).create(dest)
    site = next(dest.glob("lib/python*/site-packages"))
    for name in ("fastapi", "uvicorn", "pydantic", "openai", "anthropic"):
        (site / (name + ".py")).write_text("")
    pip = site / "pip"
    pip.mkdir()
    (pip / "__init__.py").write_text("")
    (pip / "__main__.py").write_text("""import pathlib, sys
site = pathlib.Path(__file__).resolve().parent.parent
if '-e' in sys.argv:
    target = sys.argv[sys.argv.index('-e') + 1]
    (site / 'fixture-danus.pth').write_text(target + '\\n')
""")
    # All pip calls must use python -m pip, even with a broken launcher.
    (dest / "bin/pip").write_text("#!/missing/old/python\n")
    (dest / "bin/pip").chmod(0o755)
''')
        builder.chmod(0o755)
        shutil.rmtree(self.root / "runtime/venv")
        subprocess.run([str(builder), "-m", "venv",
                        str(self.root / "runtime/venv")], check=True)
        self.bootstrap()
        return self.root / "runtime/venv"

    def test_renamed_checkout_rebuilds_venv(self):
        venv = self.real_venv_fixture()
        (venv / "old-location-marker").touch()
        moved = self.root.with_name("renamed-deployment")
        self.root.rename(moved)
        self.root = moved
        output = self.bootstrap()
        self.assertIn("relocated — rebuilding", output)
        self.assertFalse((self.root / "runtime/venv/old-location-marker").exists())
        self.assertIn("venv present + healthy", self.bootstrap())

    def test_copied_checkout_does_not_reuse_original_install(self):
        original = self.root
        venv = self.real_venv_fixture()
        (venv / "old-location-marker").touch()
        copied = original.with_name("copied-deployment")
        shutil.copytree(original, copied, symlinks=True)
        self.root = copied
        self.assertIn("relocated — rebuilding", self.bootstrap())
        self.assertTrue((venv / "old-location-marker").exists())
        self.assertFalse((copied / "runtime/venv/old-location-marker").exists())
        self.assertIn("venv present + healthy", self.bootstrap())

    def test_wrong_checkout_import_is_reinstalled(self):
        venv = self.real_venv_fixture()
        other = self.root.with_name("other checkout")
        shutil.copytree(self.root / "danus", other / "danus")
        site = next(venv.glob("lib/python*/site-packages"))
        (site / "fixture-danus.pth").write_text(str(other) + "\n")
        # A leaked PYTHONPATH must not hide the incorrect editable install.
        self.env["PYTHONPATH"] = str(self.root)
        output = self.bootstrap()
        self.assertIn("venv present + healthy", output)
        self.assertIn("installing the danus package (editable)", output)
        self.assertEqual((site / "fixture-danus.pth").read_text(), str(self.root) + "\n")


if __name__ == "__main__":
    unittest.main()
