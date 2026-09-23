from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class LockfileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.lock = json.loads((ROOT / "build.lock.json").read_text(encoding="utf-8"))

    def test_runtimes_have_url_and_sha256(self) -> None:
        for key in ("product_python", "agent_python", "node", "n8n_runtime"):
            item = self.lock[key]
            self.assertTrue(item.get("version"))
            self.assertTrue(item.get("url"))
            self.assertTrue(item.get("sha256"))
            self.assertTrue(item.get("filename"))
        self.assertEqual(self.lock["product_python"]["version"], "3.11.9")
        self.assertEqual(self.lock["agent_python"]["version"], "3.14.7")
        self.assertEqual(len(self.lock["product_python"]["sha256"]), 64)
        n8n_sha = str(self.lock["n8n_runtime"]["sha256"])
        n8n_url = str(self.lock["n8n_runtime"]["url"])
        self.assertFalse(n8n_sha.startswith("REPLACE"), "n8n_runtime.sha256 is still a template")
        self.assertNotIn("REPLACE_", n8n_url)
        self.assertEqual(len(n8n_sha), 64)

    def test_packages_are_pinned(self) -> None:
        self.assertTrue(self.lock["product_packages"])
        self.assertTrue(self.lock["agent_packages"])
        names = {p["name"] for p in self.lock["agent_packages"]}
        self.assertIn("numpy", names)
        pins = {p["name"]: p["version"] for p in self.lock["agent_packages"]}
        self.assertNotEqual(pins["numpy"], "2.2.6")
        self.assertTrue(pins["pandas"].startswith("2."))
        self.assertNotIn("scapy", names)
        self.assertNotIn("playwright", names)
        self.assertNotIn("psutil", names)
        product_names = {p["name"] for p in self.lock["product_packages"]}
        self.assertIn("opentelemetry-api", product_names)
        otel = next(p["version"] for p in self.lock["product_packages"] if p["name"] == "opentelemetry-api")
        self.assertFalse(otel.endswith("a0"))
        wheels = self.lock.get("wheels") or []
        self.assertTrue(wheels, "wheels[] must be frozen with build/pin_wheels.py")
        self.assertTrue(any(w.get("role") == "product" for w in wheels))
        self.assertTrue(any(w.get("role") == "agent" for w in wheels))
        otel_wheels = [w for w in wheels if w.get("name") == "opentelemetry-api"]
        self.assertTrue(otel_wheels)
        for item in otel_wheels:
            self.assertFalse(str(item.get("version") or "").endswith("a0"))
            self.assertGreaterEqual(tuple(int(p) for p in str(item["version"]).split(".")[:2]), (1, 28))
